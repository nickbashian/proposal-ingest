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
    max_questions_per_file: int = Field(default=5, ge=1)


class TrackerConfig(BaseModel):
    """Grants tracker ingestion settings."""

    enabled: bool = True
    path: str | None = None
    sheet_name: str | None = None
    header_row: int = Field(default=0, ge=0)
    high_authority_fields: list[str] = Field(
        default_factory=lambda: [
            "submission_date",
            "response_date",
            "selection_notification_date",
            "award_date",
            "status",
            "award_status",
            "result",
        ]
    )


class RuntimeConfig(BaseModel):
    """Top-level runtime configuration used by the CLI."""

    app: AppConfig = Field(default_factory=AppConfig)
    aws: AwsConfig = Field(default_factory=AwsConfig)
    bedrock: BedrockConfig = Field(default_factory=BedrockConfig)
    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    questions: QuestionsConfig = Field(default_factory=QuestionsConfig)


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
