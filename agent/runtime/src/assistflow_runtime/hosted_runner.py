"""Hosted runtime client. boto3 is imported only when a data-plane client is built."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from assistflow_contracts.agent import (
    AgentResult,
    AgentTrace,
    StopReason,
    TurnContext,
    Usage,
)
from pydantic import ValidationError

from assistflow_runtime.quota import SessionQuota
from assistflow_runtime.session_ref import runtime_session_id

QUOTA_MESSAGE = (
    "The assistant has reached its daily session limit. Please try again tomorrow, "
    "or wait for a person."
)
TIMEOUT_MESSAGE = "That request took too long. Please try again in a moment, or wait for a person."
TRANSPORT_MESSAGE = (
    "I could not reach the assistant. Please try again in a moment, or wait for a person."
)
UNAVAILABLE_MESSAGE = (
    "The hosted assistant is not configured. Please try again later, or wait for a person."
)


class RuntimeTimeoutError(Exception):
    """The invocation exceeded the configured timeout."""


class RuntimeTransportError(Exception):
    """The invocation failed before a usable response. One retry is allowed."""


@dataclass(frozen=True)
class RuntimeReply:
    invocation_id: str
    body: dict[str, Any]
    duration_ms: int


class RuntimeTransport(Protocol):
    """One invocation against a hosted or sandbox runtime."""

    def invoke(self, session_id: str, payload: bytes, timeout_seconds: float) -> RuntimeReply:
        """Send the turn and return the runtime document."""


class DataPlaneClient(Protocol):
    """Subset of the AgentCore data-plane client used for one invocation."""

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        """Invoke the hosted runtime and return the service response."""


class BotoRuntimeTransport:
    """Call the data plane. This type does not talk to the control plane."""

    def __init__(self, client: DataPlaneClient, runtime_arn: str) -> None:
        if runtime_arn.strip() == "":
            raise ValueError("A hosted runtime ARN is required.")
        self._client = client
        self._runtime_arn = runtime_arn

    def invoke(self, session_id: str, payload: bytes, timeout_seconds: float) -> RuntimeReply:
        started = time.perf_counter()
        try:
            response = self._client.invoke_agent_runtime(
                agentRuntimeArn=self._runtime_arn,
                runtimeSessionId=session_id,
                payload=payload,
                contentType="application/json",
                accept="application/json",
            )
        except Exception as exc:
            if _is_timeout(exc):
                raise RuntimeTimeoutError(str(exc)) from exc
            raise RuntimeTransportError(str(exc)) from exc
        if not isinstance(response, dict):
            raise RuntimeTransportError("The runtime response was not a document.")
        return RuntimeReply(
            invocation_id=_invocation_id(response),
            body=_read_body(response.get("response")),
            duration_ms=_elapsed_ms(started),
        )


class AgentCoreRuntimeRunner:
    """Delegate one turn to the hosted runtime and map the body back to AgentResult."""

    def __init__(
        self,
        transport: RuntimeTransport | None,
        quota: SessionQuota,
        *,
        timeout_seconds: float,
        arn_configured: bool = True,
    ) -> None:
        self._transport = transport
        self._quota = quota
        self._timeout = timeout_seconds
        self._arn_configured = arn_configured

    def bind(self, gateway: object) -> AgentCoreRuntimeRunner:
        """Tools run inside the hosted process. The local gateway is not a second path."""
        _ = gateway
        return self

    def run(self, turn_context: TurnContext) -> AgentResult:
        session_id = runtime_session_id(turn_context.conversation_id)
        if not self._arn_configured or self._transport is None:
            return _failed(turn_context, UNAVAILABLE_MESSAGE)
        if not self._quota.reserve(session_id):
            return _failed(turn_context, QUOTA_MESSAGE)
        payload = encode_turn(turn_context)
        started = time.perf_counter()
        try:
            reply = self._invoke(session_id, payload)
            return _with_invocation(reply)
        except RuntimeTimeoutError:
            return _failed(turn_context, TIMEOUT_MESSAGE, duration_ms=_elapsed_ms(started))
        except (RuntimeTransportError, ValidationError):
            return _failed(turn_context, TRANSPORT_MESSAGE, duration_ms=_elapsed_ms(started))

    def _invoke(self, session_id: str, payload: bytes) -> RuntimeReply:
        """Call the transport. A transport error may be retried once. A timeout is not."""
        if self._transport is None:
            raise RuntimeTransportError("The hosted runtime client is not configured.")
        transport = self._transport
        attempts = 0
        while True:
            try:
                return _attempt(transport, session_id, payload, self._timeout)
            except RuntimeTransportError:
                attempts += 1
                if attempts > 1:
                    raise


def encode_turn(turn_context: TurnContext) -> bytes:
    """Serialize the turn. The document has no customer email field."""
    return json.dumps({"turn": turn_context.model_dump(mode="json")}).encode()


def build_data_plane_client(region: str, timeout_seconds: float) -> DataPlaneClient:
    """Construct the data-plane client. Call this only when the hosted runtime is enabled."""
    import boto3  # type: ignore[import-not-found]
    from botocore.config import Config  # type: ignore[import-not-found]

    client: DataPlaneClient = boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=Config(
            retries={"max_attempts": 1},
            read_timeout=timeout_seconds,
            connect_timeout=min(timeout_seconds, 5.0),
        ),
    )
    return client


def _attempt(
    transport: RuntimeTransport,
    session_id: str,
    payload: bytes,
    timeout_seconds: float,
) -> RuntimeReply:
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(transport.invoke, session_id, payload, timeout_seconds)
    try:
        return future.result(timeout=timeout_seconds)
    except FuturesTimeoutError as exc:
        raise RuntimeTimeoutError("The runtime invocation timed out.") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _with_invocation(reply: RuntimeReply) -> AgentResult:
    document = reply.body.get("result")
    if not isinstance(document, dict):
        raise RuntimeTransportError("The runtime response did not include a turn result.")
    parsed = AgentResult.model_validate(document)
    trace = parsed.trace.model_copy(
        update={
            "runtime_invocation_id": reply.invocation_id,
            "duration_ms": reply.duration_ms,
        }
    )
    return parsed.model_copy(update={"trace": trace})


def _failed(
    turn_context: TurnContext,
    message: str,
    *,
    duration_ms: int | None = None,
) -> AgentResult:
    trace_id = uuid4()
    return AgentResult(
        assistant_message=message,
        proposed_tool_calls=[],
        trace_id=trace_id,
        stop_reason=StopReason.FAILED,
        usage=Usage(),
        trace=AgentTrace(
            id=trace_id,
            prompt_id=turn_context.prompt.id,
            prompt_version=turn_context.prompt.version,
            stop_reason=StopReason.FAILED,
            steps=[],
            provider="hosted-runtime",
            model_id="hosted-runtime",
            duration_ms=duration_ms,
        ),
        tools_handled=True,
    )


def _read_body(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    read = getattr(raw, "read", None)
    if not callable(read):
        raise RuntimeTransportError("The runtime response body could not be read.")
    decoded = read()
    if isinstance(decoded, bytes):
        decoded = decoded.decode("utf-8")
    if not isinstance(decoded, str):
        raise RuntimeTransportError("The runtime response body could not be read.")
    parsed = json.loads(decoded)
    if isinstance(parsed, dict):
        return parsed
    raise RuntimeTransportError("The runtime response body was not a document.")


def _invocation_id(response: dict[str, Any]) -> str:
    trace_id = response.get("traceId")
    if isinstance(trace_id, str) and trace_id.strip() != "":
        return trace_id
    metadata = response.get("ResponseMetadata")
    if isinstance(metadata, dict):
        request_id = metadata.get("RequestId")
        if isinstance(request_id, str) and request_id.strip() != "":
            return request_id
    return ""


def _is_timeout(exc: Exception) -> bool:
    label = f"{type(exc).__name__} {exc}".lower()
    return "timeout" in label or "timed out" in label


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
