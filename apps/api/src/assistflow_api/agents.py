"""Build the in-process assistant. The hosted client is constructed only when enabled."""

from assistflow_contracts.agent import AgentResult, AgentRunner, ModelAdapter, TurnContext
from assistflow_test_fixtures.agent_scripts import follow_up_calls, reply_from_tools, select_script

from assistflow_api.config import ExecutionMode, ModelProvider, Settings, repo_root
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import AgentLoop, ToolGateway
from assistflow_runtime.mock_adapter import MockModelAdapter
from assistflow_runtime.prompts import PromptRegistry


def build_model_adapter(settings: Settings) -> ModelAdapter:
    """Select the mock adapter unless the hosted model is explicitly enabled.

    A disabled hosted model falls back to mock. A failure while constructing
    the enabled hosted client is raised and is not replaced with the mock.
    """
    if settings.model_provider is ModelProvider.BEDROCK and settings.bedrock_enabled:
        from assistflow_runtime.hosted_model import HostedModelAdapter, build_hosted_client

        return HostedModelAdapter(
            build_hosted_client(settings.aws_region), settings.bedrock_model_id
        )
    return MockModelAdapter(select_script, follow_up_calls)


class LoopRunner:
    """Shared loop. Call `bind` with the turn's tool gateway before `run`."""

    def __init__(self, settings: Settings, adapter: ModelAdapter) -> None:
        self._settings = settings
        self._adapter = adapter
        self._loop: AgentLoop | None = None

    def bind(self, gateway: ToolGateway) -> AgentRunner:
        settings = self._settings
        runner = LoopRunner(settings, self._adapter)
        runner._loop = AgentLoop(
            adapter=self._adapter,
            gateway=gateway,
            prompts=PromptRegistry(repo_root() / "agent" / "prompts"),
            limits=TurnLimits(
                max_agent_steps=settings.max_agent_steps,
                max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
                max_model_calls_per_turn=settings.max_model_calls_per_turn,
                max_output_tokens=settings.max_output_tokens,
                max_input_tokens=settings.max_bedrock_input_tokens_per_call,
            ),
            compose=reply_from_tools,
            store_debug=(settings.trace_debug and settings.execution_mode is ExecutionMode.LOCAL),
        )
        return runner

    def run(self, turn_context: TurnContext) -> AgentResult:
        if self._loop is None:
            raise RuntimeError("Bind a tool gateway before running a turn.")
        return self._loop.run(turn_context)


def build_agent_runner(settings: Settings) -> LoopRunner | None:
    """Return the shared loop when the assistant is enabled."""
    if not settings.ai_enabled:
        return None
    return LoopRunner(settings, build_model_adapter(settings))
