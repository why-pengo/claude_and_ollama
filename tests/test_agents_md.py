"""Tests for runner/agents_md.py — AGENTS.md fetch + strict-schema parser (#107).

The parse tests cover every failure mode in docs/agents-md-schema.md's
"Parser failure modes" table; each asserts the named error AND the
schema-spec URL pointer so a target-repo author hitting the error knows
exactly where to look.
"""

import base64

import agents_md
import pytest
from agents_md import (
    SCHEMA_SPEC_URL,
    AgentsMdError,
    ParsedAgentsMd,
    VerificationCommand,
    fetch_target_agents_md,
    format_agents_summary,
    load_target_agents_md,
    parse_agents_md,
)

REPO = "why-pengo/health_track"
REF = "main"

CONFORMING = """\
# AGENTS.md — example-service

Prose the runner ignores.

## Verification commands

Free-form prose around the block is fine — the runner ignores it.

```yaml
- name: check
  command: make check
- name: test
  command: make test
```

More prose after the block.

## Conventions

```yaml
- Use SQLAlchemy 2.0 async style.
- Backend line length is 88 (Black default).
- Timestamps are timezone-aware UTC ISO strings.
```

## Repo layout

Free-form markdown the runner ignores entirely.
"""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _fake_gh(rc: int, out: str, err: str):
    def fake(args, stdin=None, timeout=120):
        return rc, out, err

    return fake


def _assert_schema_error(excinfo, *fragments: str) -> None:
    msg = str(excinfo.value)
    assert SCHEMA_SPEC_URL in msg
    for fragment in fragments:
        assert fragment in msg, f"expected {fragment!r} in error:\n{msg}"


# ---------------------------------------------------------------------------
# fetch_target_agents_md — gh transport
# ---------------------------------------------------------------------------


class TestFetchTargetAgentsMd:
    def test_returns_decoded_text_on_success(self, monkeypatch):
        monkeypatch.setattr(agents_md, "_gh", _fake_gh(0, _b64(CONFORMING), ""))
        assert fetch_target_agents_md(REPO, REF) == CONFORMING

    def test_strips_surrounding_quotes_from_jq_output(self, monkeypatch):
        # gh --jq output may carry surrounding quotes depending on output mode.
        monkeypatch.setattr(agents_md, "_gh", _fake_gh(0, f'"{_b64(CONFORMING)}"\n', ""))
        assert fetch_target_agents_md(REPO, REF) == CONFORMING

    def test_returns_none_on_404(self, monkeypatch):
        monkeypatch.setattr(agents_md, "_gh", _fake_gh(1, "", "gh: Not Found (HTTP 404)"))
        assert fetch_target_agents_md(REPO, REF) is None

    def test_non_404_error_propagates_with_context(self, monkeypatch):
        monkeypatch.setattr(
            agents_md, "_gh", _fake_gh(1, "", "gh: Internal Server Error (HTTP 500)")
        )
        with pytest.raises(AgentsMdError) as excinfo:
            fetch_target_agents_md(REPO, REF)
        msg = str(excinfo.value)
        assert REPO in msg
        assert REF in msg
        assert "HTTP 500" in msg

    def test_undecodable_content_raises_with_context(self, monkeypatch):
        # Valid base64 of bytes that aren't valid UTF-8.
        bad = base64.b64encode(b"\xff\xfe").decode("ascii")
        monkeypatch.setattr(agents_md, "_gh", _fake_gh(0, bad, ""))
        with pytest.raises(AgentsMdError) as excinfo:
            fetch_target_agents_md(REPO, REF)
        assert REPO in str(excinfo.value)


# ---------------------------------------------------------------------------
# parse_agents_md — success shape
# ---------------------------------------------------------------------------


class TestParseAgentsMdSuccess:
    def test_parses_conforming_document(self):
        parsed = parse_agents_md(CONFORMING)
        assert parsed.verification_commands == [
            VerificationCommand(name="check", command="make check"),
            VerificationCommand(name="test", command="make test"),
        ]
        assert parsed.conventions == [
            "Use SQLAlchemy 2.0 async style.",
            "Backend line length is 88 (Black default).",
            "Timestamps are timezone-aware UTC ISO strings.",
        ]

    def test_unknown_top_level_headings_are_ignored(self):
        # "## Repo layout" in CONFORMING must not confuse the parser; also
        # verify a doc where an unknown section sits BETWEEN the required ones.
        doc = CONFORMING.replace(
            "## Conventions",
            "## Where to start\n\nprose\n\n## Conventions",
        )
        parsed = parse_agents_md(doc)
        assert len(parsed.verification_commands) == 2


# ---------------------------------------------------------------------------
# parse_agents_md — one test per schema-table failure mode
# ---------------------------------------------------------------------------


class TestParseAgentsMdFailureModes:
    def test_missing_verification_heading(self):
        doc = CONFORMING.replace("## Verification commands", "## Verify commands")
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "'## Verification commands' not found")

    def test_missing_conventions_heading(self):
        doc = CONFORMING.replace("## Conventions", "## House rules")
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "'## Conventions' not found")

    def test_missing_yaml_block_under_heading(self):
        doc = "## Verification commands\n\nprose only\n\n## Conventions\n\n```yaml\n- a\n```\n"
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "no ```yaml fenced block", "'## Verification commands'")

    def test_unterminated_yaml_block(self):
        doc = "## Verification commands\n\n```yaml\n- name: check\n  command: make check\n"
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "unterminated")

    def test_yaml_parse_error_carries_library_message(self):
        doc = (
            "## Verification commands\n\n```yaml\n- name: [unclosed\n```\n\n"
            "## Conventions\n\n```yaml\n- a\n```\n"
        )
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "YAML parse error")

    def test_verification_not_a_list(self):
        doc = CONFORMING.replace(
            "- name: check\n  command: make check\n- name: test\n  command: make test",
            "name: check\ncommand: make check",
        )
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "must be a YAML list", "got dict")

    def test_entry_not_a_mapping(self):
        doc = CONFORMING.replace(
            "- name: check\n  command: make check\n- name: test\n  command: make test",
            "- make check",
        )
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "entry 0", "must be a mapping")

    def test_entry_missing_command(self):
        doc = CONFORMING.replace("- name: test\n  command: make test", "- name: test")
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "entry 1", "non-empty string 'command'")

    def test_entry_missing_name(self):
        doc = CONFORMING.replace("- name: test\n  command: make test", "- command: make test")
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "entry 1", "non-empty string 'name'")

    def test_entry_with_typo_key_rejected(self):
        # The schema's explicit guard: `cmd:` must not silently drop a command.
        doc = CONFORMING.replace("  command: make test", "  cmd: make test")
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "unexpected key(s)", "cmd")

    def test_non_string_command_rejected(self):
        doc = CONFORMING.replace("command: make test", "command: 42")
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "non-empty string 'command'")

    def test_duplicate_names_rejected(self):
        doc = CONFORMING.replace("- name: test", "- name: check")
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "reuses name 'check'", "unique")

    def test_conventions_not_a_list(self):
        doc = CONFORMING.replace(
            "- Use SQLAlchemy 2.0 async style.\n"
            "- Backend line length is 88 (Black default).\n"
            "- Timestamps are timezone-aware UTC ISO strings.",
            "style: SQLAlchemy 2.0 async",
        )
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "'## Conventions' must be a YAML list of strings")

    def test_non_string_convention_rejected(self):
        doc = CONFORMING.replace(
            "- Use SQLAlchemy 2.0 async style.",
            "- rule: Use SQLAlchemy 2.0 async style.",
        )
        with pytest.raises(AgentsMdError) as excinfo:
            parse_agents_md(doc)
        _assert_schema_error(excinfo, "'## Conventions' entry 0 must be a string")


# ---------------------------------------------------------------------------
# load_target_agents_md — the CLI pre-flight entry point
# ---------------------------------------------------------------------------


class TestLoadTargetAgentsMd:
    def test_success_returns_parsed(self, monkeypatch):
        monkeypatch.setattr(agents_md, "_gh", _fake_gh(0, _b64(CONFORMING), ""))
        parsed = load_target_agents_md(REPO, REF)
        assert [c.name for c in parsed.verification_commands] == ["check", "test"]

    def test_missing_file_rejects_with_named_error(self, monkeypatch):
        monkeypatch.setattr(agents_md, "_gh", _fake_gh(1, "", "gh: Not Found (HTTP 404)"))
        with pytest.raises(AgentsMdError) as excinfo:
            load_target_agents_md(REPO, REF)
        _assert_schema_error(excinfo, "AGENTS.md not found", REPO, REF)

    def test_malformed_file_rejects(self, monkeypatch):
        doc = CONFORMING.replace("## Conventions", "## House rules")
        monkeypatch.setattr(agents_md, "_gh", _fake_gh(0, _b64(doc), ""))
        with pytest.raises(AgentsMdError):
            load_target_agents_md(REPO, REF)


# ---------------------------------------------------------------------------
# format_agents_summary — session banner line
# ---------------------------------------------------------------------------


class TestFormatAgentsSummary:
    def test_names_and_convention_count(self):
        parsed = ParsedAgentsMd(
            verification_commands=[
                VerificationCommand(name="check", command="make check"),
                VerificationCommand(name="test", command="make test"),
            ],
            conventions=["a", "b", "c"],
        )
        assert format_agents_summary(parsed) == "verification=[check, test], 3 conventions"
