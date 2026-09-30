"""Select the in-process assistant or the hosted runtime.

The data-plane client is built only when the hosted runtime is enabled.
"""

from typing import Protocol

from assistflow_contracts.agent import AgentResult, AgentRunner, ModelAdapter, TurnContext
from assistflow_test_fixtures.agent_scripts import follow_up_calls, reply_from_tools, select_script

from assistflow_api.config import ExecutionMode, ModelProvider, Settings, repo_root
from assistflow_runtime.hosted_runner import (
    AgentCoreRuntimeRunner,
    BotoRuntimeTransport,
    RuntimeTransport,
    build_data_plane_client,
)
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import AgentLoop, ToolGateway
from assistflow_runtime.mock_adapter import MockModelAdapter
from assistflow_runtime.prompts import PromptRegistry
from assistflow_runtime.quota import SessionQuota


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


class TurnRunner(Protocol):
    """A runner that can receive the turn's tool gateway before `run`."""

    def bind(self, gateway: ToolGateway) -> AgentRunner:
        """Attach the gateway and return the runner for this turn."""


class InProcessAgentRunner:
    """Run the shared loop in this process."""

    def __init__(self, settings: Settings, adapter: ModelAdapter) -> None:
        self._settings = settings
        self._adapter = adapter
        self._loop: AgentLoop | None = None

    def bind(self, gateway: ToolGateway) -> AgentRunner:
        settings = self._settings
        runner = InProcessAgentRunner(settings, self._adapter)
        runner._loop = self.build_loop(gateway)
        return runner

    def build_loop(self, gateway: ToolGateway) -> AgentLoop:
        """Build the same loop the hosted process uses for one turn."""
        settings = self._settings
        return AgentLoop(
            adapter=self._adapter,
            gateway=gateway,
            prompts=PromptRegistry(repo_root() / "agent" / "prompts"),
            limits=TurnLimits(
                max_agent_steps=settings.max_agent_steps,
                max_tool_calls_per_turn=settings.max_tool_calls_per_turn,
                max_model_calls_per_turn=settings.max_model_calls_per_turn,
                max_output_tokens=settings.max_output_tokens,
                max_input_tokens=settings.max_bedrock_input_tokens_per_call,
                max_retrievals_per_turn=settings.max_retrievals_per_turn,
            ),
            compose=reply_from_tools,
            store_debug=(settings.trace_debug and settings.execution_mode is ExecutionMode.LOCAL),
        )

    def run(self, turn_context: TurnContext) -> AgentResult:
        if self._loop is None:
            raise RuntimeError("Bind a tool gateway before running a turn.")
        return self._loop.run(turn_context)


def build_agent_runner(
    settings: Settings,
    *,
    quota: SessionQuota | None = None,
    transport: RuntimeTransport | None = None,
) -> TurnRunner | None:
    """Return the in-process runner, or the hosted runner when that flag is on."""
    if not settings.ai_enabled:
        return None
    if settings.agentcore_enabled:
        return _hosted_runner(settings, quota, transport)
    return InProcessAgentRunner(settings, build_model_adapter(settings))


def _hosted_runner(
    settings: Settings,
    quota: SessionQuota | None,
    transport: RuntimeTransport | None,
) -> AgentCoreRuntimeRunner:
    """Build the hosted runner. An empty ARN does not construct a cloud client."""
    store = quota if quota is not None else SessionQuota(settings.max_sessions_per_day)
    if transport is not None:
        return AgentCoreRuntimeRunner(
            transport,
            store,
            timeout_seconds=settings.agentcore_invocation_timeout_seconds,
        )
    if settings.agentcore_runtime_arn.strip() == "":
        return AgentCoreRuntimeRunner(
            None,
            store,
            timeout_seconds=settings.agentcore_invocation_timeout_seconds,
            arn_configured=False,
        )
    client = build_data_plane_client(
        settings.aws_region,
        settings.agentcore_invocation_timeout_seconds,
    )
    return AgentCoreRuntimeRunner(
        BotoRuntimeTransport(client, settings.agentcore_runtime_arn),
        store,
        timeout_seconds=settings.agentcore_invocation_timeout_seconds,
    )
