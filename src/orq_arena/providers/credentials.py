"""Credential advice from the orq CLI, and one probe that the key actually works.

The arena reads its key from ``ORQ_API_KEY`` and nothing else. That is the same
precedence ``orq launch`` documents ("an exported key overrides the workspace
picked by orq auth login"), and disagreeing with the rest of a user's orq
tooling would be its own kind of surprise.

What the CLI is used for here is **advice, not tokens**. It can say whether you
are logged in and which workspace is active, which makes the error message
actionable and gives the manifest its provenance. It is deliberately not used
as a credential source: the CLI states that a login session expires after about
an hour, and a tournament routinely runs longer, so borrowing that token would
trade a loud failure at minute zero for a silent one at minute ninety.

The probe exists because the failure it catches is invisible otherwise. A stale
key produced 401 on every judge call of a real rejudge and still rendered a
leaderboard, and ``orq doctor`` reported healthy the whole time, because it
checks auth and endpoint reachability but never exercises router inference.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import cache

import httpx

from ..config import ORQ_API_KEY_ENV, OrqAIGatewayConfig
from .models_list import router_base_url

_CLI = "orq"
_CLI_TIMEOUT_S = 10


@cache
def _whoami() -> dict | None:
    """``orq auth whoami`` as a dict, or None if that is not available.

    Never raises: the CLI may be absent, logged out, an unrelated binary of the
    same name, or simply slow. All of those mean "no advice to offer", which is
    a fine answer.

    Cached for the life of the process. The active workspace cannot change
    under a running tournament, and three call sites asked independently: the
    401 branch, the hint it builds, and every manifest write. Each was a fresh
    subprocess with a ten second ceiling, one of them from inside the async
    tournament loop, where a hung CLI would stall every in-flight stream.
    """
    if shutil.which(_CLI) is None:
        return None
    # The flag that asks for JSON changed between CLI majors: 8.x takes
    # `-o json` and rejects `--json` as an unknown flag, 5.x took `--json`.
    # With only the old spelling, every 8.x install answered "unknown flag",
    # which is indistinguishable from "no advice" and silently switched the
    # whole feature off. Newest first, since that is what an install gets.
    for json_flag in (["-o", "json"], ["--json"]):
        try:
            proc = subprocess.run(  # noqa: S603
                [_CLI, "auth", "whoami", *json_flag],
                capture_output=True,
                text=True,
                timeout=_CLI_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            continue
        try:
            data = json.loads(proc.stdout)
        except (ValueError, TypeError):
            # Exit 0 with output that is not JSON: this CLI took the flag to
            # mean something else. That is the same "wrong spelling" case as a
            # nonzero exit, so the other spelling still gets its turn.
            continue
        if isinstance(data, dict):
            return data
    return None


def active_workspace() -> str | None:
    """The workspace the CLI is logged into, for the run manifest.

    A leaderboard is a claim about models as a particular workspace can reach
    them, so recording which one produced it is provenance, not decoration.
    None when unknown, which is recorded as unknown rather than guessed.

    This is the CLI's workspace, not necessarily the key's: an exported
    ``ORQ_API_KEY`` outranks the login session by design, so the two disagree
    whenever someone exported a key minted elsewhere. The manifest field is
    named ``orq_cli_workspace`` for that reason, and callers should not read it
    as a statement about where the run's traffic went.
    """
    data = _whoami()
    if not data:
        return None
    key = data.get("active_workspace_key")
    return key if isinstance(key, str) and key else None


def credential_hint() -> str:
    """The message for a run that has no key, with the commands to fix it."""
    base = f"{ORQ_API_KEY_ENV} is not set."
    workspace = active_workspace()
    if workspace:
        return (
            f"{base} The orq CLI is logged in to workspace '{workspace}', but its login "
            "session expires after about an hour and a tournament can run longer, so "
            "the arena will not borrow it. Mint a key that outlives the run:\n"
            f"    orq api-keys create --name orq-arena\n"
            f"then export it as {ORQ_API_KEY_ENV}."
        )
    return (
        f"{base} Get one with:\n"
        "    orq auth login\n"
        "    orq api-keys create --name orq-arena\n"
        f"then export it as {ORQ_API_KEY_ENV}."
    )


async def verify_credential(
    cfg: OrqAIGatewayConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[bool | None, str]:
    """One cheap call to see whether the router accepts the key.

    Returns ``(ok, detail)``. ``ok`` is True when accepted, False when the
    router rejected the credential, and **None when the question could not be
    answered** (offline, 5xx, timeout). None matters: being unable to reach the
    router is not a verdict on the key, and refusing to run on that basis would
    be wrong in exactly the situation where the user can least afford it.

    The host comes from ``router_base_url`` rather than ``cfg.base_url``, so the
    probe asks about the router the run will actually call: at default config
    that is ``ORQ_BASE_URL``, and checking a staging key against production
    answers a question nobody asked. Tests inject a ``transport``, not a client,
    so the resolved URL stays under test.

    Lists models rather than generating anything, so the check costs no tokens.
    """
    api_key = os.environ.get(ORQ_API_KEY_ENV, "")
    if not api_key:
        return False, credential_hint()

    async with httpx.AsyncClient(
        base_url=router_base_url(cfg), timeout=15.0, transport=transport
    ) as probe:
        try:
            resp = await probe.get("/models", headers={"Authorization": f"Bearer {api_key}"})
        except httpx.HTTPError as exc:
            return None, f"could not reach the router to check the credential: {exc}"

    if resp.status_code in (401, 403):
        detail = ""
        try:
            body = resp.json()
            detail = (body.get("error") or {}).get("message") or ""
        except (ValueError, AttributeError):
            pass
        workspace = active_workspace()
        where = f" The orq CLI's active workspace is '{workspace}'." if workspace else ""
        return False, (
            f"the router rejected {ORQ_API_KEY_ENV} ({resp.status_code}). {detail}{where} "
            "A key is scoped to one workspace, so a key from another will fail exactly "
            "like this. Mint one for the workspace you mean:\n"
            "    orq api-keys create --name orq-arena"
        )
    # Accepted means the router answered the question. Anything else did not:
    # a 404 from a bring-your-own endpoint with no listing route, a 429, a 5xx,
    # a redirect httpx did not follow. Reporting those as True is the same
    # failure `orq doctor` had, a healthy verdict from a check that never
    # exercised the thing it claims to cover.
    if resp.is_success:
        return True, ""
    return None, (
        f"the router answered {resp.status_code} to the credential check at "
        f"{resp.request.url}; credential not verified"
    )
