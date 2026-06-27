"""Unit tests for runner/ollama_client.py — chat client + per-turn metrics."""

import httpx
import pytest

from ollama_client import (
    extract_turn_metrics,
    format_session_metrics_summary,
    format_turn_metrics,
    ollama_chat,
)

# ---------------------------------------------------------------------------
# ollama_chat — POSTs through a caller-owned httpx.Client (#59)
#                to Ollama's native /api/chat endpoint (#78)
# ---------------------------------------------------------------------------


class TestOllamaChat:
    def test_uses_caller_provided_client_and_builds_url_payload(self):
        # Regression guard for #59: ollama_chat must accept and use the
        # client the caller passes in (so run_session can reuse a single
        # client + connection pool across every turn). Also pins the #78
        # native endpoint + envelope contract.
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            seen["url"] = str(request.url)
            seen["payload"] = _json.loads(request.content)
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "ok"}, "done_reason": "stop"},
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            resp = ollama_chat(
                client,
                "http://bazzite.local:11434",
                "qwen3.6:latest",
                [{"role": "user", "content": "hi"}],
                [{"type": "function", "function": {"name": "noop"}}],
            )

        assert seen["url"] == "http://bazzite.local:11434/api/chat"
        assert seen["payload"]["model"] == "qwen3.6:latest"
        assert seen["payload"]["stream"] is False
        assert seen["payload"]["messages"] == [{"role": "user", "content": "hi"}]
        assert seen["payload"]["tools"][0]["function"]["name"] == "noop"
        # No options passed → key must be absent from the wire payload.
        assert "options" not in seen["payload"]
        assert resp["message"]["content"] == "ok"

    def test_strips_trailing_slash_from_host(self):
        # Defensive: host=".../" should not produce "...//api/..." with a
        # double slash.
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"message": {"content": "x"}})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            ollama_chat(client, "http://example/", "m", [], [])

        assert seen["url"] == "http://example/api/chat"

    def test_raises_for_status_on_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                ollama_chat(client, "http://example", "m", [], [])

    def test_options_sent_when_non_empty(self):
        # Per-request options (num_ctx, num_gpu, seed, ...) must reach the
        # wire payload under an "options" key — this is the whole point of
        # the /api/chat swap (#78).
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            seen["payload"] = _json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": "ok"}})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            ollama_chat(
                client,
                "http://example",
                "m",
                [],
                [],
                options={"num_ctx": 65536, "num_gpu": 30, "seed": 42},
            )

        assert seen["payload"]["options"] == {"num_ctx": 65536, "num_gpu": 30, "seed": 42}

    def test_options_omitted_when_empty(self):
        # Explicit empty dict should behave the same as None: no options key
        # on the wire (lets Ollama apply its own defaults; keeps payloads lean).
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            seen["payload"] = _json.loads(request.content)
            return httpx.Response(200, json={"message": {"content": "ok"}})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            ollama_chat(client, "http://example", "m", [], [], options={})

        assert "options" not in seen["payload"]


# ---------------------------------------------------------------------------
# extract_turn_metrics / format_turn_metrics / format_session_metrics_summary
#   — Ollama /api/chat per-call timing surfacing (#88)
# ---------------------------------------------------------------------------


class TestExtractTurnMetrics:
    def test_extracts_full_metric_block(self):
        resp = {
            "message": {"content": "ok"},
            "total_duration": 9876543210,
            "load_duration": 12345678,
            "prompt_eval_count": 1234,
            "prompt_eval_duration": 234567890,
            "eval_count": 567,
            "eval_duration": 8765432109,
        }
        m = extract_turn_metrics(resp)
        assert m == {
            "prompt_eval_count": 1234,
            "prompt_eval_duration": 234567890,
            "eval_count": 567,
            "eval_duration": 8765432109,
            "total_duration": 9876543210,
            "load_duration": 12345678,
        }

    def test_partial_block_keeps_present_fields_and_nulls_missing(self):
        # Some backends / mocked responses include only a subset. Missing
        # fields must come through as None so downstream formatters can
        # render them as "?" instead of crashing.
        resp = {"message": {}, "eval_count": 100, "eval_duration": 1_000_000_000}
        m = extract_turn_metrics(resp)
        assert m == {
            "prompt_eval_count": None,
            "prompt_eval_duration": None,
            "eval_count": 100,
            "eval_duration": 1_000_000_000,
            "total_duration": None,
            "load_duration": None,
        }

    def test_returns_none_when_no_metric_fields_present(self):
        # Bare response (mocked tests, non-Ollama backends) → None signals
        # the runner to stay quiet rather than emitting an all-"?" line.
        assert extract_turn_metrics({"message": {"content": "ok"}}) is None
        assert extract_turn_metrics({}) is None


class TestFormatTurnMetrics:
    def test_renders_issue_88_format_verbatim(self):
        # 1234 prompt tokens / 0.234567890s ≈ 5260.7 t/s
        # 567 gen tokens    / 8.765432109s ≈ 64.7 t/s
        # total = 9.876543210s              → 9.9s
        m = {
            "prompt_eval_count": 1234,
            "prompt_eval_duration": 234567890,
            "eval_count": 567,
            "eval_duration": 8765432109,
            "total_duration": 9876543210,
            "load_duration": 12345678,
        }
        assert (
            format_turn_metrics(m)
            == "[metrics: prompt=1234 tok @ 5260.7 t/s | gen=567 tok @ 64.7 t/s | total=9.9s]"
        )

    def test_renders_missing_fields_as_question_marks(self):
        m = {
            "prompt_eval_count": None,
            "prompt_eval_duration": None,
            "eval_count": 567,
            "eval_duration": 8765432109,
            "total_duration": None,
            "load_duration": None,
        }
        assert (
            format_turn_metrics(m)
            == "[metrics: prompt=? tok @ ? t/s | gen=567 tok @ 64.7 t/s | total=?s]"
        )

    def test_zero_duration_renders_rate_as_question_mark(self):
        # Defensive: a zero duration would otherwise blow up with
        # ZeroDivisionError. Render as "?" instead — same as missing.
        m = {
            "prompt_eval_count": 100,
            "prompt_eval_duration": 0,
            "eval_count": 0,
            "eval_duration": 0,
            "total_duration": 0,
            "load_duration": 0,
        }
        assert (
            format_turn_metrics(m)
            == "[metrics: prompt=100 tok @ ? t/s | gen=0 tok @ ? t/s | total=0.0s]"
        )

    def test_legitimate_zero_token_count_renders_as_zero_not_question_mark(self):
        # A real zero-token turn (count==0, non-zero duration) must render
        # as "0.0 t/s", not "?" — otherwise it's indistinguishable from a
        # missing-field turn in the log. Guards against treating count==0
        # as falsy in _rate.
        m = {
            "prompt_eval_count": 100,
            "prompt_eval_duration": 100_000_000,
            "eval_count": 0,
            "eval_duration": 500_000_000,  # non-zero duration, zero tokens
            "total_duration": 600_000_000,
            "load_duration": None,
        }
        assert (
            format_turn_metrics(m)
            == "[metrics: prompt=100 tok @ 1000.0 t/s | gen=0 tok @ 0.0 t/s | total=0.6s]"
        )


class TestFormatSessionMetricsSummary:
    def test_aggregates_by_summing_tokens_and_durations(self):
        # Token-weighted rates (sum tok / sum dur), not arithmetic mean
        # of per-turn rates — that's the "effective throughput" a plot wants.
        turns = [
            {
                "prompt_eval_count": 100,
                "prompt_eval_duration": 100_000_000,  # 0.1s → 1000 t/s
                "eval_count": 50,
                "eval_duration": 1_000_000_000,  # 1.0s → 50 t/s
                "total_duration": 1_500_000_000,  # 1.5s
                "load_duration": None,
            },
            {
                "prompt_eval_count": 200,
                "prompt_eval_duration": 100_000_000,  # 0.1s → 2000 t/s
                "eval_count": 100,
                "eval_duration": 2_000_000_000,  # 2.0s → 50 t/s
                "total_duration": 2_500_000_000,  # 2.5s
                "load_duration": None,
            },
        ]
        # prompt: 300 / 0.2s = 1500.0 t/s; gen: 150 / 3.0s = 50.0 t/s; wall: 4.0s
        assert format_session_metrics_summary(turns) == (
            "[session metrics: turns=2 | prompt=300 tok @ 1500.0 t/s | "
            "gen=150 tok @ 50.0 t/s | wall=4.0s]"
        )

    def test_empty_list_still_emits_marker_line(self):
        # An exit path with zero captured metrics (mocked backend, or an
        # Ollama version that doesn't populate them) still gets a summary
        # line — the marker is useful when grepping logs for run boundaries.
        assert (
            format_session_metrics_summary([])
            == "[session metrics: turns=0 (no per-call metrics captured)]"
        )

    def test_unpaired_count_and_duration_across_turns_dont_cross_contaminate(self):
        # If turn A has count without duration, and turn B has duration
        # without count, the naive per-key sum would combine the orphan
        # count with the orphan duration and produce a nonsense rate.
        # paired_sum must require both halves on the *same turn*.
        turns = [
            {
                # Turn A: count present, duration missing → not counted.
                "prompt_eval_count": 999,
                "prompt_eval_duration": None,
                "eval_count": None,
                "eval_duration": None,
                "total_duration": None,
                "load_duration": None,
            },
            {
                # Turn B: duration present, count missing → not counted.
                "prompt_eval_count": None,
                "prompt_eval_duration": 50_000_000,
                "eval_count": None,
                "eval_duration": None,
                "total_duration": None,
                "load_duration": None,
            },
        ]
        # Both halves of the prompt pair were excluded → 0 / 0 → "?", not
        # the bogus 999 / 0.05s = 19980 t/s a naive sum would produce.
        assert format_session_metrics_summary(turns) == (
            "[session metrics: turns=2 | prompt=0 tok @ ? t/s | " "gen=0 tok @ ? t/s | wall=0.0s]"
        )

    def test_partial_per_turn_fields_dont_crash(self):
        # If some turns have missing fields (None), the aggregator should
        # skip the Nones rather than crash on sum(None, int).
        turns = [
            {
                "prompt_eval_count": 100,
                "prompt_eval_duration": 100_000_000,
                "eval_count": None,
                "eval_duration": None,
                "total_duration": 1_000_000_000,
                "load_duration": None,
            }
        ]
        # gen sums to 0 → rate renders as "?"
        assert format_session_metrics_summary(turns) == (
            "[session metrics: turns=1 | prompt=100 tok @ 1000.0 t/s | "
            "gen=0 tok @ ? t/s | wall=1.0s]"
        )
