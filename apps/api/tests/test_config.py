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
    assert settings.managed_rag_enabled is False
    assert settings.local_only_mode is False
    assert settings.database_url.endswith("@localhost:54329/assistflow")
    assert settings.max_agent_steps == 8
    assert settings.max_tool_calls_per_turn == 5
    assert settings.max_memory_events_per_session == 30
    assert settings.max_sessions_per_day == 25
    assert settings.agentcore_runtime_arn == ""
    assert settings.agentcore_invocation_timeout_seconds == 30.0


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


def test_invalid_execution_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="EXECUTION_MODE"):
        load_settings({"EXECUTION_MODE": "cloud"})
