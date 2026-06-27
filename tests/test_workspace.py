"""Tests for the workspace pre-flight + session-end restore (#106).

Each test sets up a real git repo plus a local bare repo as the "remote", so
the actual `_git` subprocess path is exercised. The bare repo is placed at a
path whose tail naturally parses to `why-pengo/health_track` (e.g.
`<tmp>/why-pengo/health_track.git`), so the origin-URL parser sees the
production-shaped owner/repo pair without any URL-rewriting trickery.
"""

import subprocess
from pathlib import Path

import pytest

from workspace import (
    WorkspaceError,
    _git,
    parse_repo_from_origin_url,
    restore_workspace,
    validate_workspace,
)

REMOTE_REPO = "why-pengo/health_track"


def _commit(repo: Path, msg: str, file_name: str = "README.md", body: str = "hello") -> None:
    (repo / file_name).write_text(body)
    _git(["add", file_name], repo)
    rc, _, err = _git(["commit", "-m", msg], repo)
    assert rc == 0, err


def _seed_workspace(tmp_path: Path, repo: str = REMOTE_REPO) -> tuple[Path, Path]:
    """Build (workspace, remote) using a bare repo whose path tail parses to `repo`.

    No URL rewriting needed: `git remote get-url origin` returns the literal
    bare-path `<tmp>/owner/name.git`, which `parse_repo_from_origin_url`
    extracts back to `owner/name`. Matches `repo` by construction.
    """
    owner, name = repo.split("/", 1)
    remote_parent = tmp_path / owner
    remote_parent.mkdir()
    remote = remote_parent / f"{name}.git"
    remote.mkdir()
    rc, _, err = _git(["init", "--bare", "-b", "main", str(remote)], tmp_path)
    assert rc == 0, err

    seed = tmp_path / "seed"
    seed.mkdir()
    rc, _, err = _git(["init", "-b", "main"], seed)
    assert rc == 0, err
    _git(["config", "user.email", "t@t"], seed)
    _git(["config", "user.name", "t"], seed)
    _commit(seed, "init")
    _git(["remote", "add", "origin", str(remote)], seed)
    _git(["push", "-u", "origin", "main"], seed)

    workspace = tmp_path / "workspace"
    rc, _, err = _git(["clone", str(remote), str(workspace)], tmp_path)
    assert rc == 0, err
    _git(["config", "user.email", "t@t"], workspace)
    _git(["config", "user.name", "t"], workspace)
    return workspace, remote


# ---------------------------------------------------------------------------
# parse_repo_from_origin_url — pure
# ---------------------------------------------------------------------------


class TestParseRepoFromOriginUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://github.com/why-pengo/health_track.git", "why-pengo/health_track"),
            ("https://github.com/why-pengo/health_track", "why-pengo/health_track"),
            ("git@github.com:why-pengo/health_track.git", "why-pengo/health_track"),
            ("git@github.com:why-pengo/health_track", "why-pengo/health_track"),
            ("ssh://git@github.com/why-pengo/health_track.git", "why-pengo/health_track"),
            ("  git@github.com:why-pengo/health_track.git\n", "why-pengo/health_track"),
        ],
    )
    def test_parses_common_remote_url_shapes(self, url, expected):
        assert parse_repo_from_origin_url(url) == expected

    def test_returns_none_for_unparseable_url(self):
        assert parse_repo_from_origin_url("not-a-url") is None

    def test_returns_none_for_empty(self):
        assert parse_repo_from_origin_url("") is None


# ---------------------------------------------------------------------------
# validate_workspace — pre-flight bail paths
# ---------------------------------------------------------------------------


class TestValidateWorkspaceBailPaths:
    def test_happy_path_does_not_raise(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        validate_workspace(workspace, REMOTE_REPO, "main")

    def test_bails_when_path_missing(self, tmp_path):
        with pytest.raises(WorkspaceError, match="does not exist"):
            validate_workspace(tmp_path / "nope", REMOTE_REPO, "main")

    def test_bails_when_path_is_a_file(self, tmp_path):
        f = tmp_path / "file"
        f.write_text("x")
        with pytest.raises(WorkspaceError, match="not a directory"):
            validate_workspace(f, REMOTE_REPO, "main")

    def test_bails_when_no_dotgit(self, tmp_path):
        d = tmp_path / "plain"
        d.mkdir()
        with pytest.raises(WorkspaceError, match="not a git repository"):
            validate_workspace(d, REMOTE_REPO, "main")

    def test_bails_when_origin_repo_doesnt_match(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        with pytest.raises(WorkspaceError, match="targeting other/repo"):
            validate_workspace(workspace, "other/repo", "main")

    def test_bails_on_modified_file(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        (workspace / "README.md").write_text("dirty")
        with pytest.raises(WorkspaceError, match="dirty"):
            validate_workspace(workspace, REMOTE_REPO, "main")

    def test_bails_on_staged_file(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        (workspace / "new.txt").write_text("x")
        _git(["add", "new.txt"], workspace)
        with pytest.raises(WorkspaceError, match="dirty"):
            validate_workspace(workspace, REMOTE_REPO, "main")

    def test_bails_on_untracked_file(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        (workspace / "untracked.txt").write_text("x")
        with pytest.raises(WorkspaceError, match="dirty"):
            validate_workspace(workspace, REMOTE_REPO, "main")

    def test_bails_when_on_wrong_branch(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        _git(["checkout", "-b", "wip"], workspace)
        with pytest.raises(WorkspaceError, match="is on branch 'wip'"):
            validate_workspace(workspace, REMOTE_REPO, "main")

    def test_bails_when_behind_base_branch(self, tmp_path):
        workspace, remote = _seed_workspace(tmp_path)
        # Push a new commit to the remote (via a sibling clone) so the
        # workspace ends up behind.
        sibling = tmp_path / "sibling"
        rc, _, err = _git(["clone", str(remote), str(sibling)], tmp_path)
        assert rc == 0, err
        _git(["config", "user.email", "t@t"], sibling)
        _git(["config", "user.name", "t"], sibling)
        _commit(sibling, "remote-progress", "second.txt", "second")
        _git(["push", "origin", "main"], sibling)
        with pytest.raises(WorkspaceError, match="behind origin/main"):
            validate_workspace(workspace, REMOTE_REPO, "main")

    def test_bails_when_ahead_of_base_branch(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        # Commit locally without pushing — workspace ends up ahead of origin.
        _commit(workspace, "local-only", "extra.txt", "extra")
        with pytest.raises(WorkspaceError, match="ahead of origin/main"):
            validate_workspace(workspace, REMOTE_REPO, "main")

    def test_bails_when_diverged_from_base_branch(self, tmp_path):
        workspace, remote = _seed_workspace(tmp_path)
        # Remote moves forward via a sibling.
        sibling = tmp_path / "sibling"
        rc, _, err = _git(["clone", str(remote), str(sibling)], tmp_path)
        assert rc == 0, err
        _git(["config", "user.email", "t@t"], sibling)
        _git(["config", "user.name", "t"], sibling)
        _commit(sibling, "remote-side", "remote.txt", "remote")
        _git(["push", "origin", "main"], sibling)
        # Workspace moves forward independently — diverged.
        _commit(workspace, "local-side", "local.txt", "local")
        with pytest.raises(WorkspaceError, match="diverged"):
            validate_workspace(workspace, REMOTE_REPO, "main")

    @pytest.mark.parametrize(
        "unsafe",
        ["-x", "--help", " main", "main\n", "main with space", "", "main;rm -rf"],
    )
    def test_bails_on_unsafe_base_branch(self, tmp_path, unsafe):
        # base_branch is user-controllable via --params; if it starts with `-`
        # or carries whitespace, git could interpret it as an option in later
        # subprocess calls. Bail at the gate instead.
        workspace, _ = _seed_workspace(tmp_path)
        with pytest.raises(WorkspaceError, match="unsafe to pass to git"):
            validate_workspace(workspace, REMOTE_REPO, unsafe)


# ---------------------------------------------------------------------------
# _git — subprocess wrapper behavior
# ---------------------------------------------------------------------------


class TestGitWrapper:
    def test_timeout_returns_synthetic_failure_instead_of_raising(self, tmp_path, monkeypatch):
        # `git fetch` against a slow remote could legitimately hit the
        # default timeout. Surfacing it as a TimeoutExpired stack trace
        # bypasses the WorkspaceError contract; return rc=124 + stderr instead.
        def boom(*a, **kw):
            raise subprocess.TimeoutExpired(cmd=a[0], timeout=kw.get("timeout", 60))

        monkeypatch.setattr(subprocess, "run", boom)
        rc, out, err = _git(["fetch", "origin", "main"], tmp_path, timeout=1)
        assert rc == 124
        assert out == ""
        assert "timed out after 1s" in err


# ---------------------------------------------------------------------------
# restore_workspace — best-effort end-of-session restore
# ---------------------------------------------------------------------------


class TestRestoreWorkspace:
    def test_noop_when_already_on_base_branch(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        restore_workspace(workspace, "main")
        rc, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], workspace)
        assert rc == 0
        assert out.strip() == "main"

    def test_checks_out_base_branch_when_elsewhere(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        _git(["checkout", "-b", "runner/issue-42"], workspace)
        restore_workspace(workspace, "main")
        rc, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], workspace)
        assert rc == 0
        assert out.strip() == "main"

    def test_does_not_delete_other_branches(self, tmp_path):
        workspace, _ = _seed_workspace(tmp_path)
        _git(["checkout", "-b", "runner/issue-42"], workspace)
        _commit(workspace, "wip", "wip.txt", "wip")
        restore_workspace(workspace, "main")
        rc, out, _ = _git(["branch", "--list", "runner/issue-42"], workspace)
        assert rc == 0
        assert "runner/issue-42" in out

    def test_silent_when_path_missing(self, tmp_path, capsys):
        restore_workspace(tmp_path / "nope", "main")
        # No raise; emits nothing because the early-exit branch doesn't print.
        out = capsys.readouterr().out
        assert "restore" not in out
