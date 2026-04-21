"""Streaming response panel — shows a warrior's live output for the turn."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class ResponsePanel(VerticalScroll):
    """A scrollable panel that appends streamed text as it arrives."""

    DEFAULT_CSS = """
    ResponsePanel {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        background: $panel-darken-2;
    }
    ResponsePanel Static {
        width: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._buffer: list[str] = []
        self._content = Static("", markup=False)

    def compose(self) -> ComposeResult:
        yield self._content

    def append_chunk(self, chunk: str) -> None:
        self._buffer.append(chunk)
        self._content.update("".join(self._buffer))
        self.scroll_end(animate=False)

    def reset(self) -> None:
        self._buffer = []
        self._content.update("")

    def set_text(self, text: str) -> None:
        self._buffer = [text]
        self._content.update(text)
        self.scroll_end(animate=False)
