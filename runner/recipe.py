"""Recipe loading, templating, completion tracking, and next-step nudges.

The runner's recipe is a YAML file that declares the model's task prompt,
the recipe-level Ollama options, and an ordered step graph. This module
owns:

- `load_recipe` — parses the YAML, applies parameter defaults, and
  templates per-step nudges so the session loop doesn't need to.
- `template_recipe` — `{{ key }}` substitution shared by the prompt and
  each step's nudge.
- `generate_branch_name` — runner-owned branch naming (#97, #98).
- `recipe_done` / `_tool_result_succeeded` — the success predicates the
  dispatch loop reads.
- `step_aware_continue_prompt` — derives the most specific nudge from
  the step graph for a no-tool-call turn.

Extracted from `run_recipe.py` so the session loop can stay focused on
turn orchestration.
"""

import re
from datetime import datetime
from pathlib import Path

import yaml


def generate_branch_name(issue_number: str, *, now: datetime | None = None) -> str:
    """Generate the working branch name for a runner session.

    Format: `runner/issue-<N>-<YYYYMMDD-HHMMSS>` (local time, seconds
    resolution). Runner-owned so back-to-back same-task invocations
    don't collide on the model's slug choice (see #97, #98).
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"runner/issue-{issue_number}-{stamp}"


def template_recipe(prompt: str, params: dict) -> str:
    """Replace {{ key }} placeholders with parameter values."""

    def sub(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        if key not in params:
            raise KeyError(
                f"Recipe references {{{{ {key} }}}} but no --params {key}=... was passed"
            )
        return str(params[key])

    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", sub, prompt)


def _as_str_list(value: object, *, field: str, step_id: str) -> list[str]:
    """Normalize a YAML scalar-or-list into list[str].

    YAML lets a single-element list be written as a bare scalar
    (`advances_on: github__issue_read`). `list("github__issue_read")` would
    silently turn that into per-character entries, breaking step detection
    with no error. Accept the scalar form, reject anything else loudly.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                raise TypeError(
                    f"step {step_id!r} {field}: expected list of strings, "
                    f"got element {item!r} of type {type(item).__name__}"
                )
        return list(value)
    raise TypeError(
        f"step {step_id!r} {field}: expected str or list of str, "
        f"got {type(value).__name__}: {value!r}"
    )


def load_recipe(path: Path, params: dict) -> tuple[str, str, list, dict]:
    """Returns (templated_prompt, recipe_title, steps, ollama_options).

    Mutates `params` to apply the recipe's declared parameter defaults for any
    key not explicitly passed — so a recipe author marking a parameter as
    optional-with-default works as advertised.

    `steps` is the recipe's step graph (see `step_aware_continue_prompt`).
    Each step's `nudge` is templated up-front so the session loop doesn't
    need to thread params through.

    `ollama_options` is the recipe's `options:` block (passed through to
    /api/chat as per-request options). CLI flags override these.
    """
    data = yaml.safe_load(path.read_text())
    title = data.get("title", "Recipe")
    raw_prompt = data["prompt"]

    for p in data.get("parameters") or []:
        key = p.get("key")
        default = p.get("default")
        if key and key not in params and default is not None:
            params[key] = default

    steps = []
    for s in data.get("steps") or []:
        step_id = s["id"]
        steps.append(
            {
                "id": step_id,
                "advances_on": _as_str_list(
                    s.get("advances_on"), field="advances_on", step_id=step_id
                ),
                "requires_prior": _as_str_list(
                    s.get("requires_prior"), field="requires_prior", step_id=step_id
                ),
                "nudge": template_recipe(s["nudge"], params) if s.get("nudge") else None,
            }
        )

    raw_options = data.get("options")
    if raw_options is not None and not isinstance(raw_options, dict):
        raise TypeError(
            f"recipe options: expected mapping (e.g. 'num_ctx: 65536'), got "
            f"{type(raw_options).__name__}: {raw_options!r}"
        )
    ollama_options = dict(raw_options or {})

    return template_recipe(raw_prompt, params), title, steps, ollama_options


def _tool_result_succeeded(result: str) -> bool:
    """True if a tool result doesn't start with the "ERROR" prefix the
    wrappers use. Centralises the "what counts as success?" predicate so
    the dispatch loop and any future caller agree on the same rule.
    """
    return not result.startswith("ERROR")


def recipe_done(succeeded: set[str]) -> bool:
    """True if create_pull_request AND add_issue_comment both succeeded.

    `succeeded` is the set of tool names that have had at least one
    non-ERROR result this session — maintained as monotonic-add-only by
    the session loop. The #55 regression guard rides on the same set:
    a failed PR call (e.g. 422 from branch protection) is never added,
    so a later successful comment call cannot flip this to True.
    """
    return "github__create_pull_request" in succeeded and "github__add_issue_comment" in succeeded


GENERIC_CONTINUE_PROMPT = (
    "You emitted no tool call this turn. The recipe is not complete. "
    "Identify which step you're on (Step 0-6) and call the next tool "
    "directly. Do not narrate. Do not summarize. Call the tool."
)


def step_aware_continue_prompt(succeeded: set[str], steps: list) -> str:
    """
    On a no-tool-call turn, return the most specific next-step instruction
    we can derive from session state. Catches the eval-20b/20c pattern
    where the model finishes Step 3 and stalls before Step 5/6 — generic
    "call a tool" prompts weren't enough; the model needs to be told
    WHICH tool comes next.

    `succeeded` is the set of tool names that have had at least one
    non-ERROR result this session — monotonic-add-only, maintained by
    the session loop. A step counts as "done" when at least one of its
    advances_on tools is in that set. The walk returns the pre-templated
    nudge of the first step whose requires_prior steps are all done but
    who isn't.
    """
    by_id = {s["id"]: s for s in steps}

    def step_done(step: dict) -> bool:
        return any(t in succeeded for t in step["advances_on"])

    for step in steps:
        if step_done(step):
            continue
        prereqs = step.get("requires_prior", [])
        if not all(p in by_id and step_done(by_id[p]) for p in prereqs):
            continue
        if step.get("nudge"):
            return step["nudge"]

    return GENERIC_CONTINUE_PROMPT
