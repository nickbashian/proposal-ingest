"""Pydantic models for inventory records, metadata, questions, usage logs, and manifests."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

APP_SCHEMA_VERSION = "0.1.0"
ConfidenceValue = Annotated[float, Field(ge=0.0, le=1.0)]


class ProcessingStrategy(StrEnum):
	direct_bedrock = "direct_bedrock"
	local_extract_then_bedrock = "local_extract_then_bedrock"
	inventory_only = "inventory_only"
	direct_bedrock_optional = "direct_bedrock_optional"


class ProcessingStatus(StrEnum):
	discovered = "discovered"
	skipped_hidden_or_system = "skipped_hidden_or_system"
	skipped_temp_office_file = "skipped_temp_office_file"
	ignored_stray_year_file = "ignored_stray_year_file"
	unsupported_file_type = "unsupported_file_type"
	inventory_only = "inventory_only"
	superseded_by_pdf = "superseded_by_pdf"
	pending_analysis = "pending_analysis"
	processed_pass1 = "processed_pass1"
	needs_context_pass2 = "needs_context_pass2"
	processed_pass2 = "processed_pass2"
	needs_user_answer = "needs_user_answer"
	included_in_clean_set = "included_in_clean_set"


class DocumentCategory(StrEnum):
	opportunity_document = "opportunity_document"
	proposal_response = "proposal_response"
	supporting_document = "supporting_document"
	budget_financial = "budget_financial"
	administrative_compliance = "administrative_compliance"
	partner_document = "partner_document"
	technical_data = "technical_data"
	report_or_deliverable = "report_or_deliverable"
	presentation = "presentation"
	internal_planning = "internal_planning"
	correspondence = "correspondence"
	unknown = "unknown"


class DocumentRole(StrEnum):
	technical_volume = "technical_volume"
	project_description = "project_description"
	commercialization_plan = "commercialization_plan"
	statement_of_work = "statement_of_work"
	budget = "budget"
	budget_justification = "budget_justification"
	quad_chart = "quad_chart"
	abstract = "abstract"
	letter_of_support = "letter_of_support"
	facilities_document = "facilities_document"
	biosketch = "biosketch"
	data_management_plan = "data_management_plan"
	current_pending_support = "current_pending_support"
	rfp = "rfp"
	foa = "foa"
	topic_description = "topic_description"
	submission_instructions = "submission_instructions"
	terms_and_conditions = "terms_and_conditions"
	dfars_clauses = "dfars_clauses"
	evaluation_criteria = "evaluation_criteria"
	award_notice = "award_notice"
	review_feedback = "review_feedback"
	milestone_report = "milestone_report"
	final_report = "final_report"
	tracker = "tracker"
	unknown = "unknown"


class OriginType(StrEnum):
	source_opportunity = "source_opportunity"
	generated_response = "generated_response"
	post_submission_feedback = "post_submission_feedback"
	award = "award"
	internal_reference = "internal_reference"
	unknown = "unknown"


class VersionStatus(StrEnum):
	final = "final"
	draft = "draft"
	template = "template"
	submitted_version = "submitted_version"
	working_version = "working_version"
	superseded = "superseded"
	unknown = "unknown"


class Agency(StrEnum):
	doe = "DOE"
	dod = "DOD"
	nsf = "NSF"
	nasa = "NASA"
	arpa_e = "ARPA-E"
	army = "Army"
	navy = "Navy"
	air_force = "Air Force"
	darpa = "DARPA"
	ohio_third_frontier = "Ohio Third Frontier"
	private = "Private"
	other = "Other"
	unknown = "unknown"


class Program(StrEnum):
	sbir = "SBIR"
	sttr = "STTR"
	foa = "FOA"
	baa = "BAA"
	prize = "Prize"
	fellowship = "Fellowship"
	accelerator = "Accelerator"
	commercial_proposal = "Commercial Proposal"
	internal_planning = "Internal Planning"
	other = "Other"
	unknown = "unknown"


class ProposalStatus(StrEnum):
	drafted = "drafted"
	submitted = "submitted"
	selected = "selected"
	awarded = "awarded"
	rejected = "rejected"
	pending = "pending"
	not_submitted = "not_submitted"
	active = "active"
	completed = "completed"
	unknown = "unknown"


class SensitivityLabel(StrEnum):
	public = "public"
	internal = "internal"
	confidential = "confidential"
	partner_confidential = "partner_confidential"
	financial_sensitive = "financial_sensitive"
	export_control_review = "export_control_review"
	personal_info = "personal_info"
	unknown = "unknown"


class RecommendedRagTreatment(StrEnum):
	full_document = "full_document"
	summary_only = "summary_only"
	metadata_only = "metadata_only"
	exclude = "exclude"
	manual_review = "manual_review"


class RagPriority(StrEnum):
	high = "high"
	medium = "medium"
	low = "low"
	exclude = "exclude"


class TrackerMatchStatus(StrEnum):
	matched = "matched"
	unmatched = "unmatched"
	ambiguous = "ambiguous"
	not_attempted = "not_attempted"


class QuestionPriority(StrEnum):
	low = "low"
	medium = "medium"
	high = "high"
	critical = "critical"


class QuestionStatus(StrEnum):
	open = "open"
	answered = "answered"
	applied = "applied"
	suppressed = "suppressed"
	skipped = "skipped"


class InventoryRecord(BaseModel):
	model_config = ConfigDict(extra="forbid")

	document_id: str
	proposal_id: str
	source_path: str
	relative_path: str
	year_folder: str
	proposal_branch: str
	file_name_original: str
	file_name_safe: str
	extension: str
	size_bytes: int = Field(ge=0)
	modified_time: str
	sha256: str = Field(min_length=64, max_length=64)
	eligible_for_processing: bool
	processing_strategy: ProcessingStrategy
	processing_status: ProcessingStatus
	skip_reason: str | None = None
	duplicate_of_document_id: str | None = None
	superseded_by_document_id: str | None = None


class SystemMetadata(BaseModel):
	model_config = ConfigDict(extra="allow")

	source_path: str
	relative_path: str
	year_folder: str
	proposal_branch: str
	file_name_original: str
	file_name_safe: str
	extension: str
	size_bytes: int = Field(ge=0)
	modified_time: str
	sha256: str = Field(min_length=64, max_length=64)
	processing_strategy: ProcessingStrategy
	processing_status: ProcessingStatus


class DocumentIdentity(BaseModel):
	model_config = ConfigDict(extra="allow")

	canonical_document_title: str
	document_category: DocumentCategory
	document_role: DocumentRole
	origin_type: OriginType
	version_status: VersionStatus
	draft_or_final_evidence: str = ""
	language: str = "unknown"
	document_date: str | None = None


class ProposalContext(BaseModel):
	model_config = ConfigDict(extra="allow")

	canonical_proposal_name: str
	proposal_short_name: str | None = None
	agency: Agency = Agency.unknown
	agency_subunit: str | None = None
	program: Program = Program.unknown
	phase: str | None = None
	topic_number: str | None = None
	topic_title: str | None = None
	solicitation_number: str | None = None
	submission_date: str | None = None
	response_date: str | None = None
	status: ProposalStatus = ProposalStatus.unknown
	award_status: str = "unknown"
	award_amount: float | None = None
	lead_organization: str | None = None
	prime_or_sub: str = "unknown"
	partners: list[str] = Field(default_factory=list)
	customer_or_sponsor: str | None = None


class PerformanceMetric(BaseModel):
	model_config = ConfigDict(extra="allow")

	metric_name: str
	value: str
	unit: str | None = None
	condition: str | None = None
	demonstrated_or_target: str | None = None
	confidence: ConfidenceValue


class TechnicalClaim(BaseModel):
	model_config = ConfigDict(extra="allow")

	claim: str
	claim_type: str
	support_level: str
	evidence_text_summary: str | None = None
	needs_verification: bool = True
	confidence: ConfidenceValue


class ContentMetadata(BaseModel):
	model_config = ConfigDict(extra="allow")

	summary_short: str = ""
	summary_detailed: str = ""
	primary_topics: list[str] = Field(default_factory=list)
	technical_keywords: list[str] = Field(default_factory=list)
	technologies: list[str] = Field(default_factory=list)
	applications: list[str] = Field(default_factory=list)
	performance_metrics: list[PerformanceMetric] = Field(default_factory=list)
	technical_claims: list[TechnicalClaim] = Field(default_factory=list)
	risks: list[str] = Field(default_factory=list)
	milestones: list[str] = Field(default_factory=list)
	deliverables: list[str] = Field(default_factory=list)


class OpportunityTreatment(BaseModel):
	model_config = ConfigDict(extra="allow")

	opportunity_context_useful: bool = False
	boilerplate_heavy: bool = False
	useful_context_summary: str = ""
	boilerplate_summary: str = ""
	recommended_rag_treatment: RecommendedRagTreatment = RecommendedRagTreatment.metadata_only


class InclusionMetadata(BaseModel):
	model_config = ConfigDict(extra="allow")

	include_in_clean_set: bool
	include_in_future_rag: bool
	rag_priority: RagPriority
	include_reason: str | None = None
	exclude_reason: str | None = None
	recommended_chunking_strategy: str | None = None

	@model_validator(mode="after")
	def validate_reason_fields(self) -> InclusionMetadata:
		if (self.include_in_clean_set or self.include_in_future_rag) and not self.include_reason:
			raise ValueError("include_reason is required when a document is included")
		if (
			not self.include_in_clean_set
			and not self.include_in_future_rag
			and not self.exclude_reason
		):
			raise ValueError("exclude_reason is required when a document is excluded")
		return self


class SensitivityMetadata(BaseModel):
	model_config = ConfigDict(extra="allow")

	sensitivity_labels: list[SensitivityLabel] = Field(default_factory=list)
	contains_budget_or_rates: bool = False
	contains_personal_info: bool = False
	contains_partner_confidential: bool = False
	contains_export_control_flags: bool = False
	manual_review_required: bool
	manual_review_reasons: list[str] = Field(default_factory=list)


class TrackerMatchingMetadata(BaseModel):
	model_config = ConfigDict(extra="allow")

	tracker_match_status: TrackerMatchStatus = TrackerMatchStatus.not_attempted
	tracker_row_id: str | None = None
	tracker_match_confidence: ConfidenceValue = 0.0
	tracker_disagreements: list[dict[str, Any]] = Field(default_factory=list)


class DocumentConfidence(BaseModel):
	model_config = ConfigDict(extra="allow")

	document_category: ConfidenceValue
	document_role: ConfidenceValue
	origin_type: ConfidenceValue
	version_status: ConfidenceValue
	canonical_proposal_name: ConfidenceValue
	agency: ConfidenceValue
	program: ConfidenceValue
	status: ConfidenceValue
	award_status: ConfidenceValue
	include_in_clean_set: ConfidenceValue
	include_in_future_rag: ConfidenceValue
	rag_priority: ConfidenceValue


class QuestionForUser(BaseModel):
	model_config = ConfigDict(extra="allow")

	question_id: str
	field: str | None = None
	question: str
	priority: QuestionPriority = QuestionPriority.medium
	suggested_options: list[str] = Field(default_factory=list)
	model_guess: str | None = None
	answer_type: str | None = None
	status: QuestionStatus = QuestionStatus.open
	notes: str | None = None


class DocumentMetadata(BaseModel):
	model_config = ConfigDict(extra="allow")

	schema_version: str = APP_SCHEMA_VERSION
	document_id: str
	proposal_id: str
	run_id: str
	system: SystemMetadata
	document_identity: DocumentIdentity
	proposal_context: ProposalContext
	content: ContentMetadata
	opportunity_treatment: OpportunityTreatment = Field(default_factory=OpportunityTreatment)
	inclusion: InclusionMetadata
	sensitivity: SensitivityMetadata
	tracker_matching: TrackerMatchingMetadata = Field(default_factory=TrackerMatchingMetadata)
	confidence: DocumentConfidence
	questions_for_user: list[QuestionForUser] = Field(default_factory=list)
	fields_needing_review: list[str] = Field(default_factory=list)
	processing_notes: list[str] = Field(default_factory=list)


class ReviewQuestion(BaseModel):
	model_config = ConfigDict(extra="allow")

	question_id: str
	run_id: str | None = None
	proposal_id: str
	document_id: str | None = None
	source_path: str | None = None
	proposal_branch: str | None = None
	file_name_original: str | None = None
	field: str | None = None
	question: str
	priority: QuestionPriority = QuestionPriority.medium
	suggested_options: str | None = None
	model_guess: str | None = None
	user_answer: str | None = None
	answer_type: str | None = None
	status: QuestionStatus = QuestionStatus.open
	created_at: str | None = None
	updated_at: str | None = None
	applied_at: str | None = None
	notes: str | None = None


class BedrockUsageRecord(BaseModel):
	model_config = ConfigDict(extra="allow")

	run_id: str
	document_id: str
	proposal_id: str
	model_id: str
	processing_strategy: str
	pass_number: int = Field(ge=1)
	start_time: str
	end_time: str
	latency_seconds: float = Field(ge=0)
	input_tokens: int | None = Field(default=None, ge=0)
	output_tokens: int | None = Field(default=None, ge=0)
	total_tokens: int | None = Field(default=None, ge=0)
	success: bool
	error_type: str | None = None
	error_message: str | None = None


class FolderKeyDocument(BaseModel):
	model_config = ConfigDict(extra="allow")

	document_id: str
	file_name_original: str | None = None
	document_role: DocumentRole | None = None
	include_in_clean_set: bool | None = None


class FolderMetadata(BaseModel):
	model_config = ConfigDict(extra="allow")

	schema_version: str = APP_SCHEMA_VERSION
	proposal_id: str
	year_folder: str
	proposal_branch: str
	canonical_proposal_name: str = "unknown"
	proposal_short_name: str | None = None
	agency: Agency = Agency.unknown
	agency_subunit: str | None = None
	program: Program = Program.unknown
	phase: str | None = None
	topic_number: str | None = None
	topic_title: str | None = None
	solicitation_number: str | None = None
	submission_date: str | None = None
	selection_notification_date: str | None = None
	award_date: str | None = None
	status: ProposalStatus = ProposalStatus.unknown
	award_status: str = "unknown"
	lead_organization: str | None = None
	prime_or_sub: str = "unknown"
	partners: list[str] = Field(default_factory=list)
	technical_focus: list[str] = Field(default_factory=list)
	commercial_focus: list[str] = Field(default_factory=list)
	folder_summary_short: str
	folder_summary_detailed: str = ""
	opportunity_context_summary: str = ""
	generated_response_summary: str = ""
	key_documents: list[FolderKeyDocument] = Field(default_factory=list)
	included_document_count: int = Field(default=0, ge=0)
	excluded_document_count: int = Field(default=0, ge=0)
	manual_review_count: int = Field(default=0, ge=0)
	open_critical_questions: int = Field(default=0, ge=0)
	ready_for_clean_set: bool
	ready_for_future_s3: bool
	tracker_match_status: TrackerMatchStatus = TrackerMatchStatus.not_attempted
	tracker_disagreements: list[dict[str, Any]] = Field(default_factory=list)


class S3ManifestRow(BaseModel):
	model_config = ConfigDict(extra="allow")

	document_id: str
	proposal_id: str
	local_clean_path: str
	metadata_path: str
	recommended_s3_key: str
	include_in_future_rag: bool
	rag_priority: RagPriority


class RunManifest(BaseModel):
	model_config = ConfigDict(extra="allow")

	schema_version: str = APP_SCHEMA_VERSION
	run_id: str
	command: str
	source_root: str
	output_root: str
	config_snapshot: dict[str, Any]
	git_commit: str | None = None
	timestamp: str
	mock_bedrock: bool = False
