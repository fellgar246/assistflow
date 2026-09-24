"""Hosted model adapter. boto3 is imported only when a client is constructed."""

import time
from typing import Any, Protocol

from assistflow_contracts.agent import (
    AdapterUsage,
    ModelMessage,
    ModelMessageRole,
    ModelProviderError,
    ModelResponse,
    ModelText,
    ModelToolUse,
    ProviderErrorCode,
    ToolSchema,
    ToolUseRequest,
)

HOSTED_PROVIDER = "bedrock"


class ConverseClient(Protocol):
    """Subset of the Bedrock Runtime Converse client used by this adapter."""

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        """Send one Converse request and return the provider response."""


class HostedModelAdapter:
    """Call the Converse API. The model id comes from configuration."""

    def __init__(self, client: ConverseClient, model_id: str) -> None:
        if model_id.strip() == "":
            raise ValueError("A hosted model id is required.")
        self._client = client
        self._model_id = model_id

    def complete(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema],
        max_output_tokens: int,
    ) -> ModelResponse:
        started = time.perf_counter()
        try:
            payload = self._client.converse(
                modelId=self._model_id,
                messages=[_converse_message(message) for message in messages if _keep(message)],
                toolConfig={"tools": [_tool_spec(tool) for tool in tools]},
                inferenceConfig={"maxTokens": max_output_tokens},
            )
        except Exception as exc:
            return ModelProviderError(
                code=_classify(exc),
                usage=AdapterUsage(),
                provider=HOSTED_PROVIDER,
                model_id=self._model_id,
                latency_ms=_elapsed_ms(started),
            )
        if not isinstance(payload, dict):
            return _malformed(self._model_id, started)
        return _parse(payload, self._model_id, _elapsed_ms(started))


def build_hosted_client(region: str) -> ConverseClient:
    """Construct a Bedrock Runtime client. Call this only when the hosted model is enabled."""
    import boto3  # type: ignore[import-not-found]

    client: ConverseClient = boto3.client("bedrock-runtime", region_name=region)
    return client


def _parse(payload: dict[str, Any], model_id: str, latency_ms: int) -> ModelResponse:
    usage = _usage(payload.get("usage"))
    output = payload.get("output")
    message = output.get("message") if isinstance(output, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return ModelProviderError(
            code=ProviderErrorCode.MALFORMED,
            usage=usage,
            provider=HOSTED_PROVIDER,
            model_id=model_id,
            latency_ms=latency_ms,
        )
    requests: list[ToolUseRequest] = []
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            return _malformed(model_id, latency_ms, usage)
        tool_use = block.get("toolUse")
        if isinstance(tool_use, dict):
            name = tool_use.get("name")
            tool_id = tool_use.get("toolUseId")
            arguments = tool_use.get("input")
            if not isinstance(name, str) or not isinstance(tool_id, str):
                return _malformed(model_id, latency_ms, usage)
            if not isinstance(arguments, dict):
                arguments = {}
            requests.append(ToolUseRequest(id=tool_id, name=name, arguments=arguments))
            continue
        text = block.get("text")
        if isinstance(text, str):
            texts.append(text)
    if requests:
        return ModelToolUse(
            requests=requests,
            usage=usage,
            provider=HOSTED_PROVIDER,
            model_id=model_id,
            latency_ms=latency_ms,
        )
    if texts:
        return ModelText(
            text="".join(texts),
            usage=usage,
            provider=HOSTED_PROVIDER,
            model_id=model_id,
            latency_ms=latency_ms,
        )
    return _malformed(model_id, latency_ms, usage)


def _usage(raw: object) -> AdapterUsage:
    if not isinstance(raw, dict):
        return AdapterUsage()
    return AdapterUsage(
        input_tokens=_non_negative(raw.get("inputTokens")),
        output_tokens=_non_negative(raw.get("outputTokens")),
    )


def _non_negative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _malformed(
    model_id: str, started_or_latency: float | int, usage: AdapterUsage | None = None
) -> ModelProviderError:
    latency = (
        started_or_latency
        if isinstance(started_or_latency, int)
        else _elapsed_ms(started_or_latency)
    )
    return ModelProviderError(
        code=ProviderErrorCode.MALFORMED,
        usage=usage or AdapterUsage(),
        provider=HOSTED_PROVIDER,
        model_id=model_id,
        latency_ms=latency,
    )


def _classify(exc: Exception) -> ProviderErrorCode:
    label = f"{type(exc).__name__} {exc}".lower()
    if "throttl" in label:
        return ProviderErrorCode.THROTTLED
    if "timeout" in label or "timed out" in label:
        return ProviderErrorCode.TIMEOUT
    return ProviderErrorCode.MALFORMED


def _converse_message(message: ModelMessage) -> dict[str, Any]:
    if message.role is ModelMessageRole.TOOL:
        return {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": message.tool_call_id or message.tool_name or "tool",
                        "content": [{"text": message.content}],
                    }
                }
            ],
        }
    role = "assistant" if message.role is ModelMessageRole.ASSISTANT else "user"
    return {"role": role, "content": [{"text": message.content}]}


def _tool_spec(tool: ToolSchema) -> dict[str, Any]:
    return {
        "toolSpec": {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": {"json": tool.input_schema},
        }
    }


def _keep(message: ModelMessage) -> bool:
    return message.content != "" or message.role is ModelMessageRole.TOOL


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
