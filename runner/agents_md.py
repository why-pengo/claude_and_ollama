"""Target-repo AGENTS.md fetch + strict-schema parser (#107).

At session start the runner fetches the target repo's root `AGENTS.md`
and parses it against the canonical schema (`docs/agents-md-schema.md`,
#105). Parsed verification commands feed the post-commit gate (#108);
conventions stay on session state only — the model reads them itself via
the recipe's Step 0 fetch, and the runner never injects them into the
system prompt (decision C on #107).

The parser is deliberately strict: a malformed AGENTS.md is more
dangerous than a missing one, because the model can fabricate conventions
to fill the void. Every failure mode in the schema's table rejects loudly
with a message specific enough to fix without reading this source, plus a
pointer to the spec.
"""

import base64
from dataclasses import dataclass
from urllib.parse import quote

import yaml

from gh import _gh

SCHEMA_SPEC_URL = (
    "https://github.com/why-pengo/claude_and_ollama/blob/main/docs/agents-md-schema.md"
)

VERIFICATION_HEADING = "## Verification commands"
CONVENTIONS_HEADING = "## Conventions"

_COMMAND_KEYS = {"name", "command"}


class AgentsMdError(Exception):
    """Missing or malformed target-repo AGENTS.md — rejects the session."""


def _schema_error(msg: str) -> AgentsMdError:
    return AgentsMdError(f"{msg}\nSchema spec: {SCHEMA_SPEC_URL}")


@dataclass(frozen=True)
class VerificationCommand:
    name: str
    command: str


@dataclass(frozen=True)
class ParsedAgentsMd:
    verification_commands: list[VerificationCommand]
    conventions: list[str]


def fetch_target_agents_md(repo: str, ref: str) -> str | None:
    """Fetch root AGENTS.md from `repo` at `ref` via `gh api`.

    Returns None on 404 (file genuinely missing). Any other gh failure
    raises AgentsMdError with repo/ref context — no retries: auth was
    validated by the pre-flight, and transient errors are rare enough
    that "print and let the user re-run" beats retry complexity
    (decision E on #107).
    """
    path = f"repos/{repo}/contents/AGENTS.md?ref={quote(ref, safe='')}"
    rc, out, err = _gh(["api", path, "--jq", ".content"])
    if rc != 0:
        if "Not Found" in err or "(HTTP 404)" in err:
            return None
        raise AgentsMdError(f"fetching AGENTS.md from {repo}@{ref} failed: {err.strip()}")
    try:
        # gh --jq output may carry surrounding quotes depending on gh's
        # output mode; strip only the ends — never interior characters.
        return base64.b64decode(out.strip().strip('"')).decode("utf-8")
    except Exception as e:
        raise AgentsMdError(f"decoding AGENTS.md content from {repo}@{ref} failed: {e}") from e


def _section_lines(text: str, heading: str) -> list[str]:
    """Lines between `heading` and the next `## ` heading (or EOF)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip() == heading:
            section = []
            for below in lines[i + 1 :]:
                if below.startswith("## "):
                    break
                section.append(below)
            return section
    raise _schema_error(f"required section heading '{heading}' not found")


def _yaml_block(section: list[str], heading: str) -> str:
    """The first ```yaml fenced block within a section's lines."""
    in_block = False
    block: list[str] = []
    for line in section:
        stripped = line.strip()
        if not in_block:
            if stripped == "```yaml":
                in_block = True
        elif stripped == "```":
            return "\n".join(block)
        else:
            block.append(line)
    if in_block:
        raise _schema_error(f"unterminated ```yaml block under '{heading}'")
    raise _schema_error(f"no ```yaml fenced block found under '{heading}'")


def _load_yaml(block: str, heading: str) -> object:
    try:
        return yaml.safe_load(block)
    except yaml.YAMLError as e:
        raise _schema_error(f"YAML parse error under '{heading}': {e}") from e


def _validate_commands(raw: object) -> list[VerificationCommand]:
    if not isinstance(raw, list):
        raise _schema_error(
            f"'{VERIFICATION_HEADING}' must be a YAML list of {{name, command}} "
            f"entries, got {type(raw).__name__}"
        )
    commands: list[VerificationCommand] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw):
        where = f"'{VERIFICATION_HEADING}' entry {i}"
        if not isinstance(entry, dict):
            raise _schema_error(f"{where} must be a mapping with keys name+command, got {entry!r}")
        extra = set(entry) - _COMMAND_KEYS
        if extra:
            # key=repr: YAML mapping keys can be non-strings, and sorting a
            # mixed-type set raises TypeError — this path must stay AgentsMdError.
            raise _schema_error(
                f"{where} has unexpected key(s) {sorted(extra, key=repr)} — only 'name' and "
                f"'command' are allowed (this guards against typos like 'cmd:' "
                f"silently dropping a command): {entry!r}"
            )
        for key in ("name", "command"):
            value = entry.get(key)
            if not isinstance(value, str) or not value.strip():
                raise _schema_error(f"{where} needs a non-empty string '{key}': {entry!r}")
        name = entry["name"]
        if name in seen:
            raise _schema_error(f"{where} reuses name '{name}' — names must be unique")
        seen.add(name)
        commands.append(VerificationCommand(name=name, command=entry["command"]))
    return commands


def _validate_conventions(raw: object) -> list[str]:
    if not isinstance(raw, list):
        raise _schema_error(
            f"'{CONVENTIONS_HEADING}' must be a YAML list of strings, got {type(raw).__name__}"
        )
    for i, entry in enumerate(raw):
        if not isinstance(entry, str):
            raise _schema_error(
                f"'{CONVENTIONS_HEADING}' entry {i} must be a string, got "
                f"{type(entry).__name__}: {entry!r}"
            )
    return list(raw)


def parse_agents_md(text: str) -> ParsedAgentsMd:
    """Parse AGENTS.md text against the canonical schema.

    Raises AgentsMdError on every failure mode in the schema's table;
    each message names the offending piece and carries the spec URL.
    """
    verification_raw = _load_yaml(
        _yaml_block(_section_lines(text, VERIFICATION_HEADING), VERIFICATION_HEADING),
        VERIFICATION_HEADING,
    )
    conventions_raw = _load_yaml(
        _yaml_block(_section_lines(text, CONVENTIONS_HEADING), CONVENTIONS_HEADING),
        CONVENTIONS_HEADING,
    )
    return ParsedAgentsMd(
        verification_commands=_validate_commands(verification_raw),
        conventions=_validate_conventions(conventions_raw),
    )


def load_target_agents_md(repo: str, ref: str) -> ParsedAgentsMd:
    """Fetch + parse the target repo's root AGENTS.md, or raise AgentsMdError.

    The single entry point the CLI pre-flight calls: missing file and
    malformed file both reject, per the schema's fail-loudly bias.
    """
    text = fetch_target_agents_md(repo, ref)
    if text is None:
        raise _schema_error(
            f"AGENTS.md not found in {repo}@{ref} — the runner requires a "
            f"conforming root AGENTS.md in the target repo"
        )
    return parse_agents_md(text)


def format_agents_summary(parsed: ParsedAgentsMd) -> str:
    """One-line session-banner summary: which commands will gate, at a glance."""
    names = ", ".join(c.name for c in parsed.verification_commands)
    return f"verification=[{names}], {len(parsed.conventions)} conventions"
