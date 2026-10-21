"""A disconnected SSE client must stop V3's LLM generation promptly.

The /v3/generate handler flags the callback when a write hits a broken pipe,
and the pipeline only checked that flag at phase boundaries. A repair phase
is several multi-thousand-token calls, so a proxy that had already given up
(the interactive cap) left V3 generating for minutes on a llama-server slot
the agent needed. LLMAdapter now checks should_abort before each request and
after every streamed token.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "v3-service"))

import adapters  # noqa: E402


class _FakeStream:
    def __init__(self, deltas):
        self._lines = [
            ("data: " + json.dumps({"choices": [{"delta": {"content": d}}]})).encode()
            for d in deltas
        ] + [b"data: [DONE]"]
        self.read_lines = 0

    def __iter__(self):
        for line in self._lines:
            self.read_lines += 1
            yield line

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(monkeypatch, stream, calls):
    def fake(req, timeout=None):
        calls.append(req.full_url)
        return stream

    monkeypatch.setattr(adapters.urllib.request, "urlopen", fake)


def test_abort_before_request_sends_nothing(monkeypatch):
    calls = []
    _fake_urlopen(monkeypatch, _FakeStream(["x"]), calls)
    llm = adapters.LLMAdapter()
    llm.should_abort = lambda: True
    with pytest.raises(adapters.ClientDisconnected):
        llm("<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n", 0.2, 64, None)
    assert calls == []


def test_abort_mid_stream_stops_after_the_current_token(monkeypatch):
    calls = []
    stream = _FakeStream(["a", "b", "c", "d", "e"])
    _fake_urlopen(monkeypatch, stream, calls)
    tokens = []
    state = {"gone": False}

    def progress(stage, detail="", **data):
        if stage == "token":
            tokens.append(detail)
            state["gone"] = True  # the write for this token hit a broken pipe

    llm = adapters.LLMAdapter(progress_callback=progress)
    llm.should_abort = lambda: state["gone"]
    with pytest.raises(adapters.ClientDisconnected):
        llm("<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n", 0.2, 64, None)
    assert tokens == ["a"]
    assert stream.read_lines == 1


def test_no_abort_hook_streams_everything(monkeypatch):
    calls = []
    _fake_urlopen(monkeypatch, _FakeStream(["a", "b", "c"]), calls)
    text, _, _ = adapters.LLMAdapter()(
        "<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\n", 0.2, 64, None)
    assert text == "abc"
    assert len(calls) == 1
