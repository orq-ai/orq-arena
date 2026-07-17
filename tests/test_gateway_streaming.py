"""stream_completion parsing: text vs think deltas, usage, finish_reason."""

from types import SimpleNamespace

from orq_arena.config import OrqAIGatewayConfig
from orq_arena.providers.orq_gateway import OrqGateway


def _delta(content=None, model_extra=None, reasoning_content=None):
    d = SimpleNamespace(content=content, model_extra=model_extra or {})
    if reasoning_content is not None:
        d.reasoning_content = reasoning_content
    return d


def _chunk(delta=None, finish_reason=None, usage=None):
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice] if delta or finish_reason else [], usage=usage)


def _usage(prompt=10, completion=5, reasoning=3):
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
    )


def _gateway(monkeypatch, chunks):
    monkeypatch.setenv("ORQ_API_KEY", "sk-test")
    gw = OrqGateway(OrqAIGatewayConfig(base_url="http://localhost:9/v1"))

    async def fake_create(**_kwargs):
        async def stream():
            for c in chunks:
                yield c

        return stream()

    monkeypatch.setattr(gw._client.chat.completions, "create", fake_create)
    return gw


async def _collect(gw, usage_out=None):
    out = []
    async for kind, text in gw.stream_completion(
        model="prov/model", prompt="hi", usage_out=usage_out
    ):
        out.append((kind, text))
    return out


async def test_text_deltas_yield_in_order(monkeypatch):
    gw = _gateway(monkeypatch, [_chunk(_delta(content="Hel")), _chunk(_delta(content="lo"))])
    assert await _collect(gw) == [("text", "Hel"), ("text", "lo")]


async def test_reasoning_delta_yields_think(monkeypatch):
    # `reasoning` on model_extra (Anthropic/Gemini spelling via the router)
    gw = _gateway(monkeypatch, [_chunk(_delta(model_extra={"reasoning": "hmm"}))])
    assert await _collect(gw) == [("think", "hmm")]


async def test_reasoning_content_spelling_yields_think(monkeypatch):
    # DeepSeek-style `reasoning_content` attribute
    gw = _gateway(monkeypatch, [_chunk(_delta(reasoning_content="pondering"))])
    assert await _collect(gw) == [("think", "pondering")]


async def test_think_and_text_in_one_delta(monkeypatch):
    gw = _gateway(
        monkeypatch, [_chunk(_delta(content="answer", model_extra={"reasoning": "step"}))]
    )
    assert await _collect(gw) == [("think", "step"), ("text", "answer")]


async def test_usage_and_finish_reason_land_in_usage_out(monkeypatch):
    chunks = [
        _chunk(_delta(content="hi")),
        _chunk(_delta(content=""), finish_reason="length"),
        _chunk(usage=_usage(prompt=11, completion=7, reasoning=4)),
    ]
    gw = _gateway(monkeypatch, chunks)
    usage_out: dict = {}
    await _collect(gw, usage_out)
    assert usage_out == {
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_tokens": 4,
        "finish_reason": "length",
    }


async def test_none_token_counts_become_zero(monkeypatch):
    usage = SimpleNamespace(
        prompt_tokens=None, completion_tokens=None, completion_tokens_details=None
    )
    gw = _gateway(monkeypatch, [_chunk(usage=usage)])
    usage_out: dict = {}
    assert await _collect(gw, usage_out) == []
    assert usage_out == {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}


async def test_empty_choices_and_empty_deltas_yield_nothing(monkeypatch):
    gw = _gateway(monkeypatch, [_chunk(), _chunk(_delta(content=None))])
    assert await _collect(gw) == []
