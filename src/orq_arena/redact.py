"""Keep secrets out of everything the arena writes, shows or prints.

A harness run hands the router key to every agent container, so an agent that
runs ``env`` prints it, and it lands in its trajectory, the dossier the jury reads,
the battle log and the HTML report. The defence is a registry of secret values and
one ``redact`` applied wherever text leaves a trial: step construction, the battle
log, every written report, the process's own stdout and stderr, and (``scrub_tree``)
the raw files Harbor and the agents leave in a trial directory.

Matching is by exact value (and its URL-encoded form), not by pattern: a pattern
that catches an unknown key format also eats code in a diff.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import quote

MASK = "[redacted]"
MIN_LEN = 12  # shorter values are not worth the false positives
_ENV_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
_SECRETS: dict[str, None] = {}  # insertion-ordered set
_MAX_SCRUB_BYTES = 64 * 1024 * 1024


def register(*values: str | None) -> None:
    """Add secret values; the value and its URL-encoded form are both masked."""
    for v in values:
        v = (v or "").strip()
        if len(v) < MIN_LEN:
            continue
        _SECRETS[v] = None
        _SECRETS[quote(v, safe="")] = None


def register_env(*names: str) -> None:
    """Register the named env vars, plus every env var that looks like a credential."""
    for name in names:
        register(os.environ.get(name))
    for name, value in os.environ.items():
        if any(w in name.upper() for w in _ENV_WORDS):
            register(value)


def secrets() -> list[str]:
    # longest first, so a value that contains another is masked whole
    return sorted(_SECRETS, key=len, reverse=True)


def redact(text: str) -> str:
    """``text`` with every registered secret replaced by ``[redacted]``."""
    if not text:
        return text
    for s in secrets():
        if s in text:
            text = text.replace(s, MASK)
    return text


def clear() -> None:
    _SECRETS.clear()


class _RedactingStream:
    """A text stream that masks secrets on write and is otherwise the stream it wraps."""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def write(self, text: str) -> int:
        return self._inner.write(redact(text))  # type: ignore[attr-defined, no-any-return]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


def install_stream_redaction() -> None:
    """Wrap this process's stdout and stderr (once). Not for the full-screen TUI."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if not isinstance(stream, _RedactingStream):
            setattr(sys, name, _RedactingStream(stream))


def scrub_file(path: Path) -> bool:
    """Mask secrets in a text file in place. True when it changed. Binary and huge files are left."""
    try:
        if path.stat().st_size > _MAX_SCRUB_BYTES:
            return False
        raw = path.read_bytes()
    except OSError:
        return False
    if b"\x00" in raw[:4096]:
        return False
    text = raw.decode("utf-8", errors="surrogateescape")
    clean = redact(text)
    if clean == text:
        return False
    path.write_text(clean, encoding="utf-8", errors="surrogateescape")
    return True


def scrub_tree(root: Path) -> int:
    """``scrub_file`` over every file under ``root`` (or ``root`` itself); the count rewritten."""
    if not _SECRETS or not root.exists():
        return 0
    files: Iterable[Path] = (
        [root] if root.is_file() else (p for p in root.rglob("*") if p.is_file())
    )
    return sum(1 for p in files if scrub_file(p))


def main(argv: list[str] | None = None) -> int:
    """``python -m orq_arena.redact PATH...``: scrub existing runs with the shell's credentials."""
    args = list(sys.argv[1:] if argv is None else argv)
    register_env("ORQ_API_KEY")
    if not _SECRETS:
        print("no credential in the environment to mask", file=sys.stderr)
        return 1
    changed = sum(scrub_tree(Path(a)) for a in args)
    print(f"{changed} file(s) rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
