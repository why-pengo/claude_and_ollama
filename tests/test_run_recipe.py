"""Unit tests for the CLI shell in runner/run_recipe.py.

Only covers the CLI-shell helpers that don't move out (per #115). The
per-module helpers (recipe, session, tools, ollama_client, prose_rescue)
live in their respective test_<module>.py files.
"""

from run_recipe import _coerce_option_value

# ---------------------------------------------------------------------------
# _coerce_option_value — --ollama-option KEY=VALUE coercion (#78)
# ---------------------------------------------------------------------------


class TestCoerceOptionValue:
    def test_coerces_int(self):
        assert _coerce_option_value("30") == 30
        assert isinstance(_coerce_option_value("30"), int)

    def test_coerces_float(self):
        assert _coerce_option_value("0.7") == 0.7
        assert isinstance(_coerce_option_value("0.7"), float)

    def test_coerces_bool(self):
        assert _coerce_option_value("true") is True
        assert _coerce_option_value("True") is True
        assert _coerce_option_value("false") is False

    def test_keeps_arbitrary_string(self):
        assert _coerce_option_value("stop_here") == "stop_here"

    def test_int_takes_precedence_over_float(self):
        # "42" is parseable as both int and float; we want the int.
        assert _coerce_option_value("42") == 42
        assert isinstance(_coerce_option_value("42"), int)
