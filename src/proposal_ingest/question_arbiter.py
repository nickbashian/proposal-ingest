"""Proposal-level question arbitration (issue #8).

Turns each synthesized proposal's ``unresolved_decisions`` into a small,
budget-capped set of human-facing ``ReviewQuestion`` records. A deterministic
Python pass always runs first (used directly in mock mode, and as the
fallback for a real Bedrock arbitration call): it assigns stable,
document-independent question IDs, suppresses candidates already resolved by
a durable human override (unless materially new conflicting evidence
appears), and enforces per-proposal and per-run question budgets. Bedrock
reasoning is optional, only refines wording/consolidation of the
already-budgeted candidates Python selected, and is never required for CI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proposal_ingest.human_overrides import (
    PROPOSAL_FIELD_MAP,
    canonical_field_key,
    coerce_field_value,
    load_human_overrides,
    output_root_from_run_dir,
)
from proposal_ingest.json_utils import parse_json_object_response
from proposal_ingest.logging_utils import get_logger
from proposal_ingest.metadata_store import MetadataStore
from proposal_ingest.path_utils import short_hash
from proposal_ingest.schemas import (
    HumanOverrideRecord,
    ProposalMetadata,
    QuestionPriority,
    QuestionStatus,
    ReviewQuestion,
    UncertaintyImpact,
    UnresolvedDecision,
    UnresolvedDecisionType,
)

logger = get_logger("question_arbiter")

_IMPACT_TO_PRIORITY: dict[UncertaintyImpact, QuestionPriority] = {
    UncertaintyImpact.critical: QuestionPriority.critical,
    UncertaintyImpact.high: QuestionPriority.high,
    UncertaintyImpact.medium: QuestionPriority.medium,
    UncertaintyImpact.low: QuestionPriority.low,
}

_PRIORITY_ORDER: dict[QuestionPriority, int] = {
    QuestionPriority.critical: 0,
    QuestionPriority.high: 1,
    QuestionPriority.medium: 2,
    QuestionPriority.low: 3,
}


def stable_proposal_question_id(
    proposal_id: str, scope: str, decision_type: str, canonical_key: str
) -> str:
    """Build a stable review-question id from proposal/scope/decision-type/canonical field.

    Independent of both document IDs and question wording, so a change in
    the affected document set or in generated question text never mints a
    new ID for what is otherwise the same underlying issue.
    """
    return f"q_{short_hash(f'{proposal_id}|{scope}|{decision_type}|{canonical_key}', length=12)}"


@dataclass
class ArbitrationResult:
    """Outcome of arbitrating every synthesized proposal's unresolved decisions."""

    run_dir: Path
    output_path: Path
    questions: list[ReviewQuestion]
    suppressed_count: int
    resolved_by_override_count: int
    proposal_count: int


def arbitrate_all_proposals(
    store: MetadataStore,
    *,
    use_mock: bool = True,
    config: Any = None,
    policies: list[dict[str, str]] | None = None,
) -> ArbitrationResult:
    """Arbitrate unresolved decisions for every synthesized proposal into review questions."""
    from proposal_ingest.config import load_knowledge_base_policies, load_runtime_config

    runtime_config = config or load_runtime_config()
    max_per_proposal = runtime_config.review.max_questions_per_proposal
    max_per_run = runtime_config.review.max_questions_per_run
    include_low_priority = runtime_config.review.include_low_priority
    resolved_policies = (
        policies
        if policies is not None
        else load_knowledge_base_policies(runtime_config.synthesis.policies_path)
    )

    output_root = output_root_from_run_dir(store.run_dir)
    overrides = load_human_overrides(output_root)
    proposals = store.load_proposal_metadata_by_id()

    all_questions: list[ReviewQuestion] = []
    suppressed_count = 0
    resolved_by_override_count = 0

    for proposal_id in sorted(proposals):
        proposal = proposals[proposal_id]
        proposal_overrides = [o for o in overrides if o.proposal_id == proposal_id]
        questions, per_suppressed, per_resolved = _arbitrate_one_proposal(
            proposal,
            overrides=proposal_overrides,
            max_questions=max_per_proposal,
            include_low_priority=include_low_priority,
            use_mock=use_mock,
            policies=resolved_policies,
            config=runtime_config,
        )
        all_questions.extend(questions)
        suppressed_count += per_suppressed
        resolved_by_override_count += per_resolved

    all_questions.sort(key=lambda q: (_PRIORITY_ORDER[q.priority], q.proposal_id, q.question_id))
    if len(all_questions) > max_per_run:
        suppressed_count += len(all_questions) - max_per_run
        all_questions = all_questions[:max_per_run]

    output_path = store.write_arbitrated_questions(all_questions)
    return ArbitrationResult(
        run_dir=store.run_dir,
        output_path=output_path,
        questions=all_questions,
        suppressed_count=suppressed_count,
        resolved_by_override_count=resolved_by_override_count,
        proposal_count=len(proposals),
    )


def _arbitrate_one_proposal(
    proposal: ProposalMetadata,
    *,
    overrides: list[HumanOverrideRecord],
    max_questions: int,
    include_low_priority: bool,
    use_mock: bool,
    policies: list[dict[str, str]] | None,
    config: Any,
) -> tuple[list[ReviewQuestion], int, int]:
    overrides_by_id = {o.question_id: o for o in overrides}

    open_candidates: list[tuple[UnresolvedDecision, str, bool]] = []
    resolved_by_override = 0
    for decision in proposal.unresolved_decisions:
        canonical_key = canonical_field_key(decision.field)
        question_id = stable_proposal_question_id(
            proposal.proposal_id, str(decision.scope), str(decision.decision_type), canonical_key
        )
        override = overrides_by_id.get(question_id)
        if override is not None:
            if not _has_conflicting_new_evidence(decision, override):
                resolved_by_override += 1
                continue
            open_candidates.append((decision, question_id, True))
            continue
        open_candidates.append((decision, question_id, False))

    questions = [
        _build_review_question(proposal, decision, question_id, reopened=reopened)
        for decision, question_id, reopened in open_candidates
    ]

    if not use_mock and questions:
        try:
            questions = _refine_with_bedrock(
                proposal,
                questions,
                overrides=overrides,
                policies=policies or [],
                config=config,
            )
        except Exception:
            logger.exception(
                "Bedrock question arbitration failed for %s; using deterministic candidates",
                proposal.proposal_id,
            )

    suppressed = 0
    if not include_low_priority:
        before = len(questions)
        questions = [q for q in questions if q.priority != QuestionPriority.low]
        suppressed += before - len(questions)

    questions.sort(key=lambda q: (_PRIORITY_ORDER[q.priority], q.question_id))
    if len(questions) > max_questions:
        suppressed += len(questions) - max_questions
        questions = questions[:max_questions]

    return questions, suppressed, resolved_by_override


def _has_conflicting_new_evidence(
    decision: UnresolvedDecision, override: HumanOverrideRecord
) -> bool:
    """Return True only when fresh evidence disagrees with a previously applied answer.

    A candidate with no current guess at all is treated as still consistent
    with the applied answer (nothing new to conflict with); a question only
    reopens when the new evidence positively points somewhere else.

    ``override.applied_value`` may be a list or a number (for list/numeric
    proposal fields), while ``decision.current_guess`` is always a plain
    string; a naive ``str()`` comparison would treat every such field as
    conflicting on every rerun purely from formatting differences (e.g.
    ``"['internal']"`` vs ``"internal"``). Coercing the guess through the
    same field spec used to validate/apply answers puts both sides in the
    same shape before comparing.
    """
    if decision.current_guess is None:
        return False

    spec = PROPOSAL_FIELD_MAP.get(canonical_field_key(override.field))
    if spec is not None:
        try:
            normalized_guess = coerce_field_value(spec, decision.current_guess)
        except ValueError:
            pass
        else:
            if spec.is_list:
                return sorted(normalized_guess) != sorted(override.applied_value or [])
            return normalized_guess != override.applied_value

    return str(decision.current_guess) != str(override.applied_value)


def _build_review_question(
    proposal: ProposalMetadata,
    decision: UnresolvedDecision,
    question_id: str,
    *,
    reopened: bool,
) -> ReviewQuestion:
    proposal_name = proposal.canonical_identity.proposal_name
    why = decision.reason_unresolved or "Evidence remains materially conflicted."
    if reopened:
        why = f"Reopened: new evidence conflicts with a previously applied answer. {why}".strip()
    guess_clause = (
        f" Current best guess: '{decision.current_guess}'." if decision.current_guess else ""
    )
    question_text = (
        f"For proposal '{proposal_name}' ({proposal.proposal_id}), what is the correct value "
        f"for '{decision.field}'?{guess_clause} {decision.reason_unresolved}"
    ).strip()

    suggested_options, answer_type = _suggested_options_and_answer_type(decision)

    return ReviewQuestion(
        question_id=question_id,
        run_id=proposal.run_id,
        proposal_id=proposal.proposal_id,
        document_id=None,
        source_path=None,
        proposal_branch=proposal.proposal_branch,
        file_name_original=None,
        field=decision.field,
        question=question_text,
        priority=_IMPACT_TO_PRIORITY[decision.downstream_impact],
        suggested_options=suggested_options,
        model_guess=decision.current_guess,
        answer_type=answer_type,
        status=QuestionStatus.open,
        scope=decision.scope,
        decision_type=decision.decision_type,
        proposal_name=proposal_name,
        affected_document_ids="|".join(decision.affected_document_ids) or None,
        model_confidence=float(decision.confidence),
        evidence_summary=decision.evidence_summary or None,
        why_human_input_is_needed=why or None,
    )


def _suggested_options_and_answer_type(decision: UnresolvedDecision) -> tuple[str | None, str]:
    """Derive CSV/GUI-facing suggested_options and answer_type from the field map.

    Reuses the same ``PROPOSAL_FIELD_MAP`` that answer application validates
    against, so a reviewer sees the same controlled choices apply-answers
    will accept — never invented separately from the enforcement logic.
    """
    if decision.decision_type == UnresolvedDecisionType.authoritative_document:
        if decision.affected_document_ids:
            return "|".join(decision.affected_document_ids), "string"
        return None, "string"

    spec = PROPOSAL_FIELD_MAP.get(canonical_field_key(decision.field))
    if spec is None:
        return None, "string"
    if spec.enum_cls is not None:
        values = sorted(item.value for item in spec.enum_cls)  # type: ignore[attr-defined]
        return " | ".join(values), "enum"
    if spec.is_list:
        return None, "list"
    return None, "string"


def _refine_with_bedrock(
    proposal: ProposalMetadata,
    questions: list[ReviewQuestion],
    *,
    overrides: list[HumanOverrideRecord],
    policies: list[dict[str, str]],
    config: Any,
) -> list[ReviewQuestion]:
    """Optionally ask Bedrock to consolidate/word candidates; Python keeps IDs and budgets.

    The model may drop candidates (resolving them without a human question)
    and may rewrite ``question``/``suggested_options``/``why_human_input_is_needed``,
    but every returned entry must reuse a ``question_id`` Python already
    assigned — unrecognized IDs are silently discarded rather than trusted.
    """
    from proposal_ingest.bedrock_client import (
        call_converse_with_text,
        create_bedrock_runtime_client,
    )
    from proposal_ingest.config import load_runtime_config
    from proposal_ingest.prompts import (
        load_question_arbiter_system_prompt,
        render_question_arbiter_user_prompt,
    )

    runtime_config = config or load_runtime_config()
    packet = {
        "proposal": {
            "proposal_id": proposal.proposal_id,
            "proposal_name": proposal.canonical_identity.proposal_name,
            "canonical_identity": proposal.canonical_identity.model_dump(mode="json"),
        },
        "candidate_questions": [q.model_dump(mode="json") for q in questions],
        "prior_human_overrides": [o.model_dump(mode="json") for o in overrides],
        "standing_policies": policies,
    }
    prompt = render_question_arbiter_user_prompt(json.dumps(packet, indent=2, sort_keys=True))

    client = create_bedrock_runtime_client(runtime_config)
    raw_text, _usage = call_converse_with_text(
        client,
        model_id=runtime_config.bedrock.model_id,
        system_prompt=load_question_arbiter_system_prompt(),
        user_prompt=prompt,
        max_tokens=runtime_config.bedrock.max_tokens,
        temperature=runtime_config.bedrock.temperature,
    )
    parsed = parse_json_object_response(raw_text)
    refined = parsed.get("questions")
    if not isinstance(refined, list):
        return questions

    by_id = {q.question_id: q for q in questions}
    result: list[ReviewQuestion] = []
    for item in refined:
        if not isinstance(item, dict):
            continue
        question_id = item.get("question_id")
        if not isinstance(question_id, str):
            continue
        base = by_id.get(question_id)
        if base is None:
            continue
        updates: dict[str, Any] = {}
        for key in ("question", "suggested_options", "why_human_input_is_needed"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                updates[key] = value.strip()
        result.append(base.model_copy(update=updates) if updates else base)
    return result or questions
