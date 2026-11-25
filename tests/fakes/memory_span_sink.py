"""A fake tracing sink: collects the spans Langfuse would send, so tests can inspect them.

Pass it to `build_tracing(..., span_exporter=sink)`. No network, no keys. `block` makes `export`
wait, to model a slow or unreachable Langfuse.
"""

import json
import threading
from collections.abc import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class MemorySpanSink(SpanExporter):
    def __init__(self, block: threading.Event | None = None) -> None:
        self.spans: list[ReadableSpan] = []
        self._block = block
        self.entered = threading.Event()  # set when an export starts

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.entered.set()
        if self._block is not None:
            self._block.wait(timeout=30)
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def everything_sent(self) -> str:
        """Every value a wire format could carry: names, attributes, status, events, links."""
        parts: list[object] = []
        for span in self.spans:
            parts += [span.name, dict(span.attributes or {}), span.status.description]
            parts += [dict(span.resource.attributes)]
            for event in span.events:
                parts += [event.name, dict(event.attributes or {})]
            for link in span.links:
                parts += [dict(link.attributes or {})]
        return json.dumps(parts, default=str)
