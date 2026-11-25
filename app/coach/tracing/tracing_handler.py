"""The one place that knows Langfuse's LangChain handler internals."""

from typing import Literal

from langfuse.langchain import CallbackHandler


class MaskedCallbackHandler(CallbackHandler):
    """Langfuse's handler, except error text never leaves: only the error class name does.

    The SDK copies `str(error)` into the span status, which the export-stage mask cannot patch,
    and provider errors can echo the request. The no-text test goes through this class, so an SDK
    change to the method below fails that test instead of leaking.
    """

    def _get_error_level_and_status_message(
        self, error: BaseException
    ) -> tuple[Literal["DEFAULT", "ERROR"], str]:
        level, _ = super()._get_error_level_and_status_message(error)
        return level, type(error).__name__
