"""What the coach needs from tracing, and nothing about the vendor."""

from collections.abc import Mapping
from typing import Protocol

from langchain_core.runnables import RunnableConfig

Metadata = Mapping[str, str | int | float]


class TracedCall(Protocol):
    """One traced model call: its LangChain config, and a way to record how it ended."""

    @property
    def config(self) -> RunnableConfig: ...

    @property
    def trace_id(self) -> str: ...

    def finish(self, outcome: str) -> None:
        """Record the outcome (ok, cancelled, blocked, failed). Never raises."""
        ...


class UntracedCall:
    """What a call is when tracing is off or could not start: it traces nothing."""

    config: RunnableConfig = {}
    trace_id = ""

    def finish(self, outcome: str) -> None:
        pass


class Tracing(Protocol):
    def start_call(self, *, session_id: str, metadata: Metadata) -> TracedCall:
        """Begin one traced call. Never raises: on failure the call is simply untraced."""
        ...

    def close(self) -> None:
        """Send pending traces, waiting at most a fixed time. Never raises."""
        ...
