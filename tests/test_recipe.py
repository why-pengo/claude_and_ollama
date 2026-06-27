"""Unit tests for runner/recipe.py — loading, templating, completion gates, nudges."""

import textwrap
from datetime import datetime
from pathlib import Path

import pytest

import run_recipe
from recipe import (
    GENERIC_CONTINUE_PROMPT,
    _tool_result_succeeded,
    generate_branch_name,
    load_recipe,
    recipe_done,
    step_aware_continue_prompt,
    template_recipe,
)
from run_recipe import build_parser

# ---------------------------------------------------------------------------
# _tool_result_succeeded — predicate that gates success-set membership.
# Lives at the dispatch loop now; tested here as the source of truth for
# the "ERROR prefix = failure" rule that was the #55 regression.
# ---------------------------------------------------------------------------


class TestToolResultSucceeded:
    def test_non_error_result_counts(self):
        assert _tool_result_succeeded('{"number": 71}') is True

    def test_error_prefixed_result_does_not_count(self):
        # This is the #55 regression guard — a failed PR call returns text
        # starting with "ERROR" and must not be credited as a success.
        assert _tool_result_succeeded("ERROR opening PR: 422 head already has open PR") is False

    def test_bare_error_prefix(self):
        assert _tool_result_succeeded("ERROR") is False

    def test_empty_result_counts(self):
        # An empty tool result isn't a failure — some tools return ""
        # on success (e.g. mid-run with no payload).
        assert _tool_result_succeeded("") is True


# ---------------------------------------------------------------------------
# recipe_done — set membership check
# ---------------------------------------------------------------------------


class TestRecipeDone:
    def test_true_when_both_succeeded(self):
        assert recipe_done({"github__create_pull_request", "github__add_issue_comment"}) is True

    def test_false_when_pr_missing(self):
        # The #55 bug: a failed PR call (not in `succeeded`) followed by a
        # successful comment must NOT count as done — the branch would orphan.
        assert recipe_done({"github__add_issue_comment"}) is False

    def test_false_when_comment_missing(self):
        assert recipe_done({"github__create_pull_request"}) is False

    def test_false_on_empty(self):
        assert recipe_done(set()) is False


# ---------------------------------------------------------------------------
# step_aware_continue_prompt — derive next-step nudge from the recipe graph
# ---------------------------------------------------------------------------


STEPS_FIXTURE = [
    {
        "id": "read_issue",
        "advances_on": ["github__issue_read"],
        "requires_prior": [],
        "nudge": "NUDGE_READ_ISSUE",
    },
    {
        "id": "branch",
        "advances_on": ["github__create_branch"],
        "requires_prior": ["read_issue"],
        "nudge": "NUDGE_BRANCH",
    },
    {
        "id": "write",
        "advances_on": ["github__push_files", "github__create_or_update_file"],
        "requires_prior": ["branch"],
        "nudge": "NUDGE_WRITE",
    },
    {
        "id": "pr",
        "advances_on": ["github__create_pull_request"],
        "requires_prior": ["write"],
        "nudge": "NUDGE_PR",
    },
    {
        "id": "comment",
        "advances_on": ["github__add_issue_comment"],
        "requires_prior": ["pr"],
        "nudge": "NUDGE_COMMENT",
    },
]


class TestStepAwareContinuePrompt:
    def test_returns_first_step_nudge_when_nothing_done(self):
        assert step_aware_continue_prompt(set(), STEPS_FIXTURE) == "NUDGE_READ_ISSUE"

    def test_advances_to_branch_after_issue_read(self):
        assert step_aware_continue_prompt({"github__issue_read"}, STEPS_FIXTURE) == "NUDGE_BRANCH"

    def test_advances_to_write_after_branch(self):
        succeeded = {"github__issue_read", "github__create_branch"}
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_WRITE"

    def test_advances_to_pr_after_push_files(self):
        succeeded = {"github__issue_read", "github__create_branch", "github__push_files"}
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_PR"

    def test_advances_to_pr_after_create_or_update_file(self):
        # Either write tool counts — they share an advances_on entry
        succeeded = {
            "github__issue_read",
            "github__create_branch",
            "github__create_or_update_file",
        }
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_PR"

    def test_advances_to_comment_after_pr(self):
        succeeded = {
            "github__issue_read",
            "github__create_branch",
            "github__push_files",
            "github__create_pull_request",
        }
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_COMMENT"

    def test_falls_back_when_all_done(self):
        succeeded = {
            "github__issue_read",
            "github__create_branch",
            "github__push_files",
            "github__create_pull_request",
            "github__add_issue_comment",
        }
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == GENERIC_CONTINUE_PROMPT

    def test_errored_pr_call_does_not_advance_to_comment(self):
        # A failed create_pull_request never enters `succeeded` (the dispatch
        # loop's `_tool_result_succeeded` gate keeps it out), so the PR step
        # is still pending and its nudge fires. Branch doesn't orphan.
        succeeded = {"github__issue_read", "github__create_branch", "github__push_files"}
        assert step_aware_continue_prompt(succeeded, STEPS_FIXTURE) == "NUDGE_PR"

    def test_empty_steps_returns_generic_fallback(self):
        assert step_aware_continue_prompt(set(), []) == GENERIC_CONTINUE_PROMPT

    def test_skips_step_with_null_nudge(self):
        # A step without a nudge exists for prereq tracking only — the
        # walk should continue to the next eligible step instead of
        # falling through to the generic prompt.
        steps = [
            {
                "id": "read_issue",
                "advances_on": ["github__issue_read"],
                "requires_prior": [],
                "nudge": None,
            },
            {
                "id": "branch",
                "advances_on": ["github__create_branch"],
                "requires_prior": ["read_issue"],
                "nudge": "NUDGE_BRANCH",
            },
        ]
        # Nothing done yet → first step's nudge is None, walk continues,
        # but second step's prereq isn't met → falls through to generic.
        assert step_aware_continue_prompt(set(), steps) == GENERIC_CONTINUE_PROMPT


# ---------------------------------------------------------------------------
# generate_branch_name — runner-owned working-branch slug (#97, #98)
# ---------------------------------------------------------------------------


class TestGenerateBranchName:
    def test_shape_with_injected_time(self):
        # Inject a fixed datetime so the test isn't time-dependent.
        fixed = datetime(2026, 6, 27, 9, 30, 15)
        assert generate_branch_name("51", now=fixed) == "runner/issue-51-20260627-093015"

    def test_uses_seconds_resolution(self):
        # The format must include seconds — manual back-to-back invocations
        # don't fire within the same second, so seconds is enough disambiguation.
        fixed = datetime(2026, 1, 2, 3, 4, 5)
        assert generate_branch_name("1", now=fixed).endswith("-20260102-030405")

    def test_default_now_uses_real_clock(self):
        # No `now=` arg → uses datetime.now(). The shape is enough to assert.
        name = generate_branch_name("42")
        assert name.startswith("runner/issue-42-")
        # `YYYYMMDD-HHMMSS` = 15 chars after the prefix
        assert len(name) == len("runner/issue-42-") + 15


# ---------------------------------------------------------------------------
# template_recipe — {{ key }} substitution
# ---------------------------------------------------------------------------


class TestTemplateRecipe:
    def test_substitutes_known_keys(self):
        prompt = "Issue #{{ issue_number }} in {{ repo }}."
        result = template_recipe(prompt, {"issue_number": "51", "repo": "owner/repo"})
        assert result == "Issue #51 in owner/repo."

    def test_handles_whitespace_around_key(self):
        prompt = "{{issue_number}} and {{  issue_number  }}"
        result = template_recipe(prompt, {"issue_number": "51"})
        assert result == "51 and 51"

    def test_raises_key_error_on_missing_key(self):
        with pytest.raises(KeyError, match="repo"):
            template_recipe("PR for {{ repo }}", {"issue_number": "51"})

    def test_substitutes_branch_param(self):
        # The runner-owned branch name (#98) flows through the same
        # template_recipe path as every other recipe param.
        prompt = "Use branch {{ branch }} from {{ base_branch }}."
        result = template_recipe(
            prompt,
            {"branch": "runner/issue-51-20260627-093015", "base_branch": "develop"},
        )
        assert result == "Use branch runner/issue-51-20260627-093015 from develop."

    def test_system_prompt_renders_without_branch_param(self):
        # Regression guard for the PR #99 review finding: the system prompt
        # is loaded for every recipe (including non-issue ones like
        # plan-epic.yaml that have no issue_number → no branch param). Any
        # {{ branch }} reference here would KeyError on those recipes.
        from session import SYSTEM_PROMPT_PATH

        # Mirrors the params a non-issue recipe would arrive with — just
        # base_branch, no issue_number / branch.
        template_recipe(SYSTEM_PROMPT_PATH.read_text(), {"base_branch": "main"})


# ---------------------------------------------------------------------------
# load_recipe — honors YAML-declared parameter defaults
# ---------------------------------------------------------------------------


class TestLoadRecipe:
    def test_fills_in_declared_defaults(self, tmp_path):
        # This is the ae87496 fix — load_recipe used to ignore the YAML's
        # parameters: block, raising KeyError on optional-with-default params.
        recipe = tmp_path / "execute-issue.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: Execute GitHub Issue
                parameters:
                  - key: issue_number
                    requirement: required
                  - key: repo
                    requirement: optional
                    default: why-pengo/claude_and_ollama
                  - key: base_branch
                    requirement: optional
                    default: main
                prompt: |
                  Issue #{{ issue_number }} in {{ repo }} on {{ base_branch }}.
                """))
        params = {"issue_number": "51"}
        prompt, title, _steps, _opts = load_recipe(recipe, params)
        assert title == "Execute GitHub Issue"
        assert "Issue #51 in why-pengo/claude_and_ollama on main." in prompt
        # Mutated in place so the caller can use the resolved values too
        assert params["repo"] == "why-pengo/claude_and_ollama"
        assert params["base_branch"] == "main"

    def test_explicit_params_win_over_defaults(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                parameters:
                  - key: repo
                    requirement: optional
                    default: default/repo
                prompt: |
                  {{ repo }}
                """))
        params = {"repo": "override/repo"}
        prompt, _, _, _ = load_recipe(recipe, params)
        assert "override/repo" in prompt

    def test_returns_empty_steps_when_block_absent(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                prompt: |
                  hi
                """))
        _, _, steps, _ = load_recipe(recipe, {})
        assert steps == []

    def test_parses_steps_and_templates_nudges(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                steps:
                  - id: write
                    advances_on: [github__push_files]
                    requires_prior: [branch]
                    nudge: |
                      Open PR for #{{ issue_number }}.
                prompt: |
                  hi
                """))
        _, _, steps, _ = load_recipe(recipe, {"issue_number": "42"})
        assert steps == [
            {
                "id": "write",
                "advances_on": ["github__push_files"],
                "requires_prior": ["branch"],
                "nudge": "Open PR for #42.\n",
            }
        ]

    def test_coerces_scalar_advances_on_into_single_element_list(self, tmp_path):
        # A recipe author writing `advances_on: github__issue_read` (scalar
        # rather than a list) used to silently become a list of characters.
        # Now coerced to ["github__issue_read"].
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                steps:
                  - id: read_issue
                    advances_on: github__issue_read
                    requires_prior: branch
                    nudge: noop
                prompt: |
                  hi
                """))
        _, _, steps, _ = load_recipe(recipe, {})
        assert steps[0]["advances_on"] == ["github__issue_read"]
        assert steps[0]["requires_prior"] == ["branch"]

    def test_rejects_non_string_in_advances_on_list(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                steps:
                  - id: read_issue
                    advances_on: [42]
                    nudge: noop
                prompt: |
                  hi
                """))
        with pytest.raises(TypeError, match="advances_on"):
            load_recipe(recipe, {})

    def test_parses_options_block(self, tmp_path):
        # Recipe-level Ollama options carry through as the 4th tuple element
        # so run_session can merge them with CLI overrides.
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                options:
                  num_ctx: 65536
                  num_gpu: 30
                prompt: |
                  hi
                """))
        _, _, _, opts = load_recipe(recipe, {})
        assert opts == {"num_ctx": 65536, "num_gpu": 30}

    def test_rejects_non_mapping_options(self, tmp_path):
        # A scalar under `options:` is almost certainly an authoring typo
        # (`options: 65536` instead of `options:\n  num_ctx: 65536`).
        # Surface it loudly, not as a downstream dict()-coercion error.
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                options: 65536
                prompt: |
                  hi
                """))
        with pytest.raises(TypeError, match="recipe options"):
            load_recipe(recipe, {})

    def test_returns_empty_options_when_block_absent(self, tmp_path):
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                prompt: |
                  hi
                """))
        _, _, _, opts = load_recipe(recipe, {})
        assert opts == {}

    def test_rejects_unexpected_advances_on_type(self, tmp_path):
        # A dict (or any non-str, non-list, non-None) at the field level is
        # almost certainly an authoring typo; surface it loudly.
        recipe = tmp_path / "r.yaml"
        recipe.write_text(textwrap.dedent("""\
                title: r
                steps:
                  - id: read_issue
                    advances_on: {tool: github__issue_read}
                    nudge: noop
                prompt: |
                  hi
                """))
        with pytest.raises(TypeError, match="advances_on"):
            load_recipe(recipe, {})


# ---------------------------------------------------------------------------
# build_parser + execute-issue.yaml — runner defaults pinned to ADR-0008
# ---------------------------------------------------------------------------


class TestRunnerDefaults:
    """Pins the defaults that ADR-0008 declares: model and recipe temperature.

    If these regress, the runner's no-arg invocation has silently drifted off
    the recommended configuration. The bake-off methodology (3-of-3 against
    the canonical task) sets the bar for changing them; landing such a change
    without updating these tests should fail CI and surface the omission.
    """

    def test_default_model_is_qwen25_coder_per_adr_0008(self, monkeypatch):
        monkeypatch.delenv("RUNNER_MODEL", raising=False)
        # build_parser reads RUNNER_MODEL at parser-build time, so the
        # monkeypatch has to land before this call.
        parser = build_parser()
        assert parser.get_default("model") == "qwen2.5-coder:32b"

    def test_runner_model_env_var_still_overrides_default(self, monkeypatch):
        # The override path is the production escape hatch for picking
        # qwen3.6:latest (or any other model) without editing the runner.
        # If this regresses, evals using a non-default model break silently.
        monkeypatch.setenv("RUNNER_MODEL", "qwen3.6:latest")
        parser = build_parser()
        assert parser.get_default("model") == "qwen3.6:latest"

    def test_execute_issue_recipe_ships_temperature_0_2(self):
        # ADR-0008 says the recipe ships `temperature=0.2` as the default
        # per-request Ollama option. Anchored at the recipe level rather
        # than as a runner-wide default so a non-default recipe gets to
        # pick its own temperature.
        recipe_path = Path(run_recipe.__file__).resolve().parent.parent / (
            "recipes/execute-issue.yaml"
        )
        # execute-issue.yaml requires issue_number + repo for template
        # substitution; provide dummies so load_recipe gets to the
        # options block we want to inspect.
        _, _, _, opts = load_recipe(
            recipe_path,
            {"issue_number": "0", "repo": "x/y", "base_branch": "main", "branch": "b"},
        )
        assert opts.get("temperature") == 0.2
