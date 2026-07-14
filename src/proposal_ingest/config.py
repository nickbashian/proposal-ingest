"""Load runtime configuration from YAML, .env, environment, and CLI overrides."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default_config.yaml"
DEFAULT_KNOWLEDGE_BASE_POLICIES_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "knowledge_base_policies.yaml"
)


class AppConfig(BaseModel):
    """Application-level runtime settings."""

    schema_version: str = "0.1.0"
    output_root: str | None = None
    source_root: str | None = None
    log_level: str = "INFO"


class AwsConfig(BaseModel):
    """AWS session settings."""

    profile: str | None = "proposal-assistant"
    region: str = "us-east-1"


class BedrockConfig(BaseModel):
    """Bedrock model settings."""

    model_label: str = "opus-4.6"
    model_id: str = "us.anthropic.claude-opus-4-6-v1"
    max_direct_upload_mb: int = Field(default=20, ge=1)
    save_raw_model_responses: bool = True
    mock_bedrock: bool = False
    temperature: float = 0
    max_tokens: int = Field(default=4096, ge=1)
    retry_invalid_json_once: bool = True


class ProcessingConfig(BaseModel):
    """Document processing and strategy settings."""

    direct_upload_default: bool = True
    excel_local_extract_first: bool = True
    local_extract_max_chars: int = Field(default=200_000, ge=1_000)
    tiny_excel_max_sheets: int = Field(default=3, ge=1)
    tiny_excel_max_nonempty_cells: int = Field(default=500, ge=1)
    tiny_excel_max_size_mb: float = Field(default=1.0, ge=0.0)
    ocr_enabled: bool = False
    pass2_enabled: bool = True
    pass2_confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    stop_before_clean_set_if_critical_questions: bool = True


class QuestionsConfig(BaseModel):
    """Human-review question export settings."""

    suppress_low_priority: bool = True
    target_questions_per_file: int = Field(default=3, ge=1)


class ReviewConfig(BaseModel):
    """Proposal-level question arbitration budgets (issue #8).

    These are safeguards, not production targets: the arbiter should
    normally return far fewer questions than these caps allow.
    """

    max_questions_per_proposal: int = Field(default=3, ge=0)
    max_questions_per_run: int = Field(default=20, ge=0)
    include_low_priority: bool = False


class CleanSetConfig(BaseModel):
    """Clean-set copy behavior."""

    sanitize_filenames: bool = True
    flatten_documents_folder: bool = True
    copy_excluded_files: bool = False
    require_manual_review_clearance: bool = True


class S3ManifestConfig(BaseModel):
    """Local S3 manifest generation settings."""

    enabled: bool = True
    base_prefix: str = "proposal-history"


class TrackerConfig(BaseModel):
    """Grants tracker ingestion settings."""

    enabled: bool = True
    path: str | None = None
    sheet_name: str | None = None
    header_row: int = Field(default=0, ge=0)


class SynthesisConfig(BaseModel):
    """Proposal-level synthesis settings."""

    policies_path: str | None = None
    max_full_text_documents: int = Field(default=8, ge=0)
    max_full_text_chars_per_doc: int = Field(default=6_000, ge=1_000)


class RuntimeConfig(BaseModel):
    """Top-level runtime configuration used by the CLI."""

    app: AppConfig = Field(default_factory=AppConfig)
    aws: AwsConfig = Field(default_factory=AwsConfig)
    bedrock: BedrockConfig = Field(default_factory=BedrockConfig)
    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    questions: QuestionsConfig = Field(default_factory=QuestionsConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    clean_set: CleanSetConfig = Field(default_factory=CleanSetConfig)
    s3_manifest: S3ManifestConfig = Field(default_factory=S3ManifestConfig)
    synthesis: SynthesisConfig = Field(default_factory=SynthesisConfig)


def load_runtime_config(
    config_path: str | Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> RuntimeConfig:
    """Load runtime config with precedence CLI overrides > env > YAML > defaults."""
    load_dotenv()

    raw_config = _load_yaml_config(
        Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    )
    merged: dict[str, Any] = {}
    _deep_merge(merged, raw_config)
    _apply_environment_overrides(merged)
    if overrides:
        _deep_merge(merged, dict(overrides))
    return RuntimeConfig.model_validate(merged)


def load_knowledge_base_policies(path: str | Path | None = None) -> list[dict[str, str]]:
    """Load standing knowledge-base treatment policies used by proposal synthesis."""
    policies_path = Path(path) if path is not None else DEFAULT_KNOWLEDGE_BASE_POLICIES_PATH
    if not policies_path.exists():
        raise FileNotFoundError(f"Knowledge base policies file not found: {policies_path}")

    with policies_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict):
        raise ValueError(
            f"Knowledge base policies file must contain a top-level mapping: {policies_path}"
        )

    policies = loaded.get("policies", [])
    if not isinstance(policies, list):
        raise ValueError(f"'policies' must be a list in {policies_path}")
    return policies


def _load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a top-level mapping: {path}")
    return loaded


def _apply_environment_overrides(config: dict[str, Any]) -> None:
    env_map: dict[str, tuple[str, str, type[Any]]] = {
        "PROPOSAL_INGEST_SOURCE_ROOT": ("app", "source_root", str),
        "PROPOSAL_INGEST_OUTPUT_ROOT": ("app", "output_root", str),
        "PROPOSAL_INGEST_LOG_LEVEL": ("app", "log_level", str),
        "AWS_PROFILE": ("aws", "profile", str),
        "AWS_REGION": ("aws", "region", str),
        "BEDROCK_MODEL_ID": ("bedrock", "model_id", str),
        "BEDROCK_MODEL_LABEL": ("bedrock", "model_label", str),
        "MAX_DIRECT_UPLOAD_MB": ("bedrock", "max_direct_upload_mb", int),
        "SAVE_RAW_MODEL_RESPONSES": ("bedrock", "save_raw_model_responses", bool),
        "MOCK_BEDROCK": ("bedrock", "mock_bedrock", bool),
        "PROPOSAL_INGEST_TRACKER_PATH": ("tracker", "path", str),
        "PROPOSAL_INGEST_KB_POLICIES_PATH": ("synthesis", "policies_path", str),
    }

    for env_name, (section, key, value_type) in env_map.items():
        raw_value = os.getenv(env_name)
        if raw_value is None:
            continue

        section_values = config.setdefault(section, {})
        if not isinstance(section_values, dict):
            raise ValueError(f"Config section '{section}' must be a mapping")
        section_values[key] = _coerce_env_value(raw_value, value_type)


def _coerce_env_value(raw_value: str, value_type: type[Any]) -> Any:
    if value_type is bool:
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean environment value: {raw_value}")
    return value_type(raw_value)


def _deep_merge(base: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
            continue
        if isinstance(value, Mapping):
            base[key] = dict(value)
            continue
        base[key] = value
    return base
