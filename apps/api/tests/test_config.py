"""Execution profile resolution."""

import pytest

from assistflow_api.config import ExecutionMode, RagProvider, load_settings, repo_root


def test_repo_root_is_the_product_directory() -> None:
    assert (repo_root() / "docker-compose.yml").is_file()


def test_missing_environment_resolves_to_local_profile() -> None:
    settings = load_settings({})

    assert settings.execution_mode is ExecutionMode.LOCAL
    assert settings.aws_enabled is False
    assert settings.agentcore_enabled is False
    assert settings.bedrock_enabled is False
    assert settings.rag_provider is RagProvider.LOCAL
    assert settings.ai_enabled is True
    assert settings.long_term_memory_enabled is False
    assert settings.short_term_memory_enabled is False
    assert settings.agentcore_memory_id == ""
    assert settings.managed_rag_enabled is False
    assert settings.local_only_mode is False
    assert settings.database_url.endswith("@localhost:54329/assistflow")
    assert settings.max_agent_steps == 8
    assert settings.max_tool_calls_per_turn == 5
    assert settings.max_memory_events_per_session == 30
    assert settings.max_sessions_per_day == 25
    assert settings.agentcore_runtime_arn == ""
    assert settings.agentcore_invocation_timeout_seconds == 30.0
    assert settings.agentcore_gateway_url == ""
    assert settings.agentcore_gateway_token == ""
    assert settings.agentcore_actor_context_secret == ""
    assert settings.knowledge_bucket == ""
    assert settings.knowledge_key_prefix == "tenants/{tenant_id}/"
    assert settings.managed_knowledge_base_id == ""
    assert settings.managed_knowledge_bases == {}
    assert settings.managed_rag_metadata_key == ""
    assert settings.guardrails_enabled is False
    assert settings.guardrail_id == ""
    assert settings.guardrail_version == "DRAFT"
    assert settings.guardrail_harmful_content_strength == "MEDIUM"
    assert settings.guardrail_denied_topic_strength == "HIGH"
    assert settings.guardrail_sensitive_information_strength == "HIGH"
    assert settings.guardrail_prompt_attack_strength == "HIGH"
    assert settings.guardrail_contextual_grounding_threshold is None


def test_aws_demo_profile_enables_hosted_agent_and_model_only() -> None:
    settings = load_settings({"EXECUTION_MODE": "aws-demo"})

    assert settings.execution_mode is ExecutionMode.AWS_DEMO
    assert settings.aws_enabled is True
    assert settings.agentcore_enabled is True
    assert settings.bedrock_enabled is True
    assert settings.rag_provider is RagProvider.LOCAL
    assert settings.long_term_memory_enabled is False
    assert settings.managed_rag_enabled is False


def test_explicit_flag_overrides_profile_default() -> None:
    settings = load_settings({"EXECUTION_MODE": "aws-demo", "AWS_ENABLED": "false"})

    assert settings.aws_enabled is False
    assert settings.agentcore_enabled is True


def test_local_only_mode_forces_hosted_features_off() -> None:
    settings = load_settings(
        {
            "EXECUTION_MODE": "showcase",
            "LOCAL_ONLY_MODE": "true",
            "AWS_ENABLED": "true",
            "AGENTCORE_ENABLED": "true",
            "BEDROCK_ENABLED": "true",
            "MANAGED_RAG_ENABLED": "true",
            "LONG_TERM_MEMORY_ENABLED": "true",
            "RAG_PROVIDER": "managed",
            "GUARDRAILS_ENABLED": "true",
        }
    )

    assert settings.local_only_mode is True
    assert settings.aws_enabled is False
    assert settings.agentcore_enabled is False
    assert settings.bedrock_enabled is False
    assert settings.managed_rag_enabled is False
    assert settings.long_term_memory_enabled is False
    assert settings.rag_provider is RagProvider.LOCAL
    assert settings.ai_enabled is True
    assert settings.guardrails_enabled is False


def test_invalid_guardrail_strength_is_rejected() -> None:
    with pytest.raises(ValueError, match="GUARDRAIL_HARMFUL_CONTENT_STRENGTH"):
        load_settings({"GUARDRAIL_HARMFUL_CONTENT_STRENGTH": "extreme"})


def test_invalid_execution_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="EXECUTION_MODE"):
        load_settings({"EXECUTION_MODE": "cloud"})


def test_invalid_rag_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="local, s3, or managed"):
        load_settings({"RAG_PROVIDER": "pinecone"})


def test_managed_provider_requires_the_flag() -> None:
    with pytest.raises(ValueError, match="MANAGED_RAG_ENABLED"):
        load_settings({"RAG_PROVIDER": "managed", "MANAGED_RAG_ENABLED": "false"})


def test_local_only_mode_forces_s3_retrieval_back_to_local() -> None:
    settings = load_settings(
        {
            "LOCAL_ONLY_MODE": "true",
            "RAG_PROVIDER": "s3",
            "KNOWLEDGE_BUCKET": "assistflow-knowledge",
        }
    )

    assert settings.rag_provider is RagProvider.LOCAL
    assert settings.aws_enabled is False
