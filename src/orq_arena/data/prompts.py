"""Prompt loaders: local JSONL files and orq.ai Datasets.

JSONL format: one JSON object per line with at least a ``prompt`` key;
optional ``category`` feeds the per-category ELO slices (untagged rows land
in ``"general"``). Any other keys ride along as ``metadata`` and are carried
onto every battle record for that prompt, so rounds in ``battles.jsonl`` can
be joined back to the source data.

``orq:<dataset_id>`` instead of a file path pulls the datapoints of an
orq.ai Dataset via the orq-python SDK (same API key as the gateway): the
last user message becomes the prompt, ``{{var}}`` placeholders filled from
the datapoint's ``inputs``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PromptItem:
    text: str
    category: str = "general"
    # Opaque pass-through: never sliced or judged on, only carried to the log.
    metadata: dict = field(default_factory=dict)


def load_prompts(path: str | Path, api_key_env: str = "ORQ_API_KEY") -> list[PromptItem]:
    """Return the prompts in file (or dataset) order."""
    if str(path).startswith("orq:"):
        return _load_orq_dataset(str(path)[len("orq:") :], api_key_env)
    p = Path(path)
    out: list[PromptItem] = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            text = row.get("prompt") or row.get("text")
            if not text:
                continue
            meta = {k: v for k, v in row.items() if k not in ("prompt", "text", "category")}
            out.append(
                PromptItem(text=text, category=row.get("category") or "general", metadata=meta)
            )
    return out


def _content_text(content: Any) -> str | None:
    """Chat content is a string or a list of parts; keep the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for part in content:
            text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
            if text:
                pieces.append(text)
        return "\n".join(pieces) or None
    return None


def datapoint_to_prompt(inputs: dict | None, messages: list | None) -> PromptItem | None:
    """Map one orq.ai datapoint to a PromptItem, or None if it has no user turn.

    Arena rounds are single-prompt, so multi-turn datapoints flatten to their
    last user message; assistant/system turns are ignored.
    """
    text: str | None = None
    for m in messages or []:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if role == "user":
            text = _content_text(content) or text
    if not text:
        return None
    for key, value in (inputs or {}).items():
        # lambda replacement: dataset values are literals, not regex templates
        # (a backslash in code/LaTeX inputs must not become a group reference)
        text = re.sub(
            r"\{\{\s*" + re.escape(str(key)) + r"\s*\}\}", lambda _m, v=str(value): v, text
        )
    return PromptItem(text=text)


def orq_dataset_meta(dataset_id: str, api_key_env: str = "ORQ_API_KEY") -> dict:
    """Report metadata for an orq.ai Dataset: id, display name, studio URL.

    The name fetch is best-effort; on any failure the id doubles as the name
    so the report never blocks on this call.
    """
    import os

    name = None
    try:
        from orq_ai_sdk import Orq

        with Orq(api_key=os.environ.get(api_key_env, "")) as client:
            name = client.datasets.retrieve(dataset_id=dataset_id).display_name
    except Exception:
        pass
    return {
        "id": dataset_id,
        "name": name or dataset_id,
        "url": f"https://my.orq.ai/datasets/{dataset_id}",
    }


def _load_orq_dataset(dataset_id: str, api_key_env: str) -> list[PromptItem]:
    import os

    from orq_ai_sdk import Orq

    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise RuntimeError(
            f"{api_key_env} is not set; it is needed to fetch dataset {dataset_id!r}."
        )
    out: list[PromptItem] = []
    skipped = 0
    with Orq(api_key=api_key) as client:
        after: str | None = None
        while True:
            page = client.datasets.list_datapoints(
                dataset_id=dataset_id, limit=50, starting_after=after
            )
            rows = list(page.data or [])
            for dp in rows:
                item = datapoint_to_prompt(
                    getattr(dp, "inputs", None), getattr(dp, "messages", None)
                )
                if item:
                    dp_id = getattr(dp, "id", None)
                    out.append(replace(item, metadata={"datapoint_id": dp_id} if dp_id else {}))
                else:
                    skipped += 1
            if not rows or not getattr(page, "has_more", False):
                break
            after = rows[-1].id
    if not out:
        raise ValueError(
            f"dataset {dataset_id!r} yielded no usable prompts "
            f"({skipped} datapoint(s) without a user message)"
        )
    return out
