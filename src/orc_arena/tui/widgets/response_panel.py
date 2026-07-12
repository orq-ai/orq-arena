"""Streaming response panel — live output, thinking state, tokens/sec footer."""

from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Static


class ResponsePanel(Vertical):
    """Scrollable streamed text + a thinking window + a stats footer.

    States: idle → thinking (timer ticking, optional dimmed CoT lines) →
    streaming (tokens/sec estimate) → complete (exact usage) or error.
    """

    DEFAULT_CSS = """
    ResponsePanel {
        height: 1fr;
        border: round $primary;
        background: $panel-darken-2;
    }
    ResponsePanel.side-a { border: round $accent; }
    ResponsePanel.side-b { border: round $primary; }
    ResponsePanel #scroll { height: 1fr; padding: 0 1; }
    ResponsePanel #scroll Static { width: auto; }
    ResponsePanel #thinking-window {
        height: auto;
        max-height: 4;
        padding: 0 1;
        color: $text-muted;
        display: none;
    }
    ResponsePanel.thinking #thinking-window { display: block; }
    ResponsePanel #footer {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $panel-darken-3;
    }
    """

    def __init__(self, side: str = "a", **kwargs) -> None:
        super().__init__(**kwargs)
        self.add_class(f"side-{side}")
        self._content = Static("", markup=False)
        self._thinking_w = Static("", id="thinking-window", markup=False)
        self._footer = Static("", id="footer")
        self._buffer: list[str] = []
        self._think_lines: list[str] = []
        self._started_at: float = 0.0
        self._first_chunk_at: float | None = None
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield self._thinking_w
        with VerticalScroll(id="scroll"):
            yield self._content
        yield self._footer

    # --- state transitions -------------------------------------------------

    def reset(self) -> None:
        """New round: enter the waiting/thinking state."""
        self._buffer = []
        self._think_lines = []
        self._first_chunk_at = None
        self._started_at = time.monotonic()
        self._content.update("")
        self._thinking_w.update("")
        self.remove_class("thinking")
        self._footer.update("[dim]waiting…[/dim]")
        if self._timer is None:
            self._timer = self.set_interval(0.5, self._tick)
        else:
            self._timer.resume()

    def _tick(self) -> None:
        if self._first_chunk_at is not None:
            return
        elapsed = time.monotonic() - self._started_at
        if elapsed >= 1.5:
            self._footer.update(f"🧠 thinking… {elapsed:4.1f}s")

    def append_thinking(self, text: str) -> None:
        """Best-effort dimmed CoT: rolling window of the last ~3 lines."""
        self.add_class("thinking")
        self._think_lines = (("\n".join(self._think_lines) + text).splitlines() or [""])[-3:]
        self._thinking_w.update("\n".join(self._think_lines))

    def append_chunk(self, chunk: str) -> None:
        now = time.monotonic()
        if self._first_chunk_at is None:
            self._first_chunk_at = now
        self._buffer.append(chunk)
        self._content.update("".join(self._buffer))
        self.query_one("#scroll", VerticalScroll).scroll_end(animate=False)
        elapsed = max(now - self._first_chunk_at, 0.25)
        approx_tok = len("".join(self._buffer)) // 4
        self._footer.update(f"≈{approx_tok} tok · {approx_tok / elapsed:.0f} tok/s")

    def complete(
        self,
        *,
        tokens_out: int = 0,
        reasoning_tokens: int = 0,
        finish_reason: str = "",
        error: str | None = None,
    ) -> None:
        if self._timer is not None:
            self._timer.pause()
        self.remove_class("thinking")
        if error:
            self._footer.update("[red]✕ stream failed — round void[/red]")
            return
        total = time.monotonic() - self._started_at
        parts = [f"{tokens_out or len(''.join(self._buffer)) // 4} tok", f"{total:.1f}s"]
        if reasoning_tokens:
            parts.append(f"🧠 {reasoning_tokens} reasoning tok")
        if finish_reason == "length":
            parts.append("✂ truncated")
        self._footer.update(" · ".join(parts))
