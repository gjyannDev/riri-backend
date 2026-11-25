"""A fake `Tracing`: records what the coach asked of it and gives the chain a recording callback."""

from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from app.coach.tracing.tracing_call import Metadata


class _Recorder(BaseCallbackHandler):
    """Proves the call's config reached the chain: keeps the metadata the model run saw."""

    def __init__(self, seen: list[dict[str, Any]]) -> None:
        self._seen = seen

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._seen.append(dict(metadata or {}))


class FakeCall:
    def __init__(self, tracing: FakeTracing, trace_id: str, config: RunnableConfig) -> None:
        self._tracing = tracing
        self.trace_id = trace_id
        self.config = config

    def finish(self, outcome: str) -> None:
        self._tracing.outcomes.append(outcome)


class FakeTracing:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.outcomes: list[str] = []
        self.chain_metadata: list[dict[str, Any]] = []
        self.closed = 0

    def start_call(self, *, session_id: str, metadata: Metadata) -> FakeCall:
        self.starts.append({"session_id": session_id, "metadata": dict(metadata)})
        config = RunnableConfig(
            callbacks=[_Recorder(self.chain_metadata)],
            metadata={"langfuse_session_id": session_id, **metadata},
        )
        return FakeCall(self, f"trace-{len(self.starts)}", config)

    def close(self) -> None:
        self.closed += 1
