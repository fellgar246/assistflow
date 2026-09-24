"""Build the in-process assistant. Cloud model SDKs are not imported here."""

from assistflow_contracts.agent import AgentRunner
from assistflow_test_fixtures.agent_scripts import select_script

from assistflow_api.config import Settings, repo_root
from assistflow_runtime import MockAgentRunner, PromptRegistry, TurnLimits


def build_agent_runner(settings: Settings) -> AgentRunner | None:
    """Return the mock runner when the assistant is enabled."""
    if not settings.ai_enabled:
        return None
    return MockAgentRunner(
        prompts=PromptRegistry(repo_root() / "agent" / "prompts"),
        limits=TurnLimits(
            max_agent_steps=settings.max_agent_steps,
            max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
            max_model_calls_per_turn=settings.max_model_calls_per_turn,
        ),
        select_plan=select_script,
    )
