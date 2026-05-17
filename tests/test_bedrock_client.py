"""Tests for Bedrock client config loading and smoke test wiring."""

from __future__ import annotations

from pathlib import Path

from proposal_ingest.bedrock_client import call_converse_with_document, smoke_test_bedrock
from proposal_ingest.config import load_runtime_config


def test_load_runtime_config_prefers_environment_over_yaml(tmp_path: Path, monkeypatch) -> None:
    """Environment variables should override the YAML Bedrock and AWS settings."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "aws:",
                "  profile: yaml-profile",
                "  region: us-west-2",
                "bedrock:",
                "  model_id: yaml-model",
                "  model_label: yaml-label",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AWS_PROFILE", "env-profile")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "env-model")
    monkeypatch.setenv("BEDROCK_MODEL_LABEL", "env-label")

    config = load_runtime_config(config_path)

    assert config.aws.profile == "env-profile"
    assert config.aws.region == "us-east-1"
    assert config.bedrock.model_id == "env-model"
    assert config.bedrock.model_label == "env-label"


def test_smoke_test_bedrock_uses_converse_api(monkeypatch) -> None:
    """The smoke test should create a Bedrock Runtime client and call Converse."""
    captured: dict[str, object] = {}

    class FakeClient:
        def converse(self, **kwargs):
            captured["converse_kwargs"] = kwargs
            return {
                "output": {
                    "message": {
                        "content": [{"text": "Bedrock is reachable."}],
                    }
                },
                "usage": {
                    "inputTokens": 5,
                    "outputTokens": 4,
                    "totalTokens": 9,
                },
            }

    class FakeSession:
        def __init__(self, profile_name=None):
            captured["profile_name"] = profile_name

        def client(self, service_name, region_name=None):
            captured["service_name"] = service_name
            captured["region_name"] = region_name
            return FakeClient()

    monkeypatch.setattr("proposal_ingest.bedrock_client.boto3.Session", FakeSession)

    config = load_runtime_config(
        overrides={
            "aws": {"profile": "proposal-assistant", "region": "us-east-1"},
            "bedrock": {
                "model_id": "us.anthropic.claude-opus-4-6-v1",
                "model_label": "opus-4.6",
                "max_tokens": 4096,
                "temperature": 0,
            },
        }
    )

    result = smoke_test_bedrock(config, prompt="ping")

    assert captured["profile_name"] == "proposal-assistant"
    assert captured["service_name"] == "bedrock-runtime"
    assert captured["region_name"] == "us-east-1"
    assert captured["converse_kwargs"] == {
        "modelId": "us.anthropic.claude-opus-4-6-v1",
        "messages": [{"role": "user", "content": [{"text": "ping"}]}],
        "inferenceConfig": {"maxTokens": 128, "temperature": 0.0},
    }
    assert result.model_id == "us.anthropic.claude-opus-4-6-v1"
    assert result.region == "us-east-1"
    assert result.response_text == "Bedrock is reachable."
    assert result.total_tokens == 9


def test_call_converse_with_document_sanitizes_document_name() -> None:
    """DocumentBlock names should comply with Bedrock's restricted character set."""
    captured: dict[str, object] = {}

    class FakeClient:
        def converse(self, **kwargs):
            captured["converse_kwargs"] = kwargs
            return {
                "output": {
                    "message": {
                        "content": [{"text": "ok"}],
                    }
                },
                "usage": {},
            }

    response_text, _usage = call_converse_with_document(
        FakeClient(),
        model_id="model",
        system_prompt="system",
        user_prompt="user",
        file_bytes=b"%PDF-1.7",
        doc_format="pdf",
        doc_name="Quad_Chart.v2 [Final].pdf",
        max_tokens=128,
        temperature=0,
    )

    document_block = captured["converse_kwargs"]["messages"][0]["content"][0]["document"]
    assert document_block["name"] == "Quad Chart v2 [Final]"
    assert response_text == "ok"
