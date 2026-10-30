"""Offline local-repository checks for atomic, branch-separated publication."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/publish_synthetic.sh"


def git(directory: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(directory), *arguments], text=True
    ).strip()


@pytest.fixture()
def repositories(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
    )
    repo = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", str(remote), str(repo)], check=True, capture_output=True
    )
    git(repo, "config", "user.name", "reviewer")
    git(repo, "config", "user.email", "reviewer@example.invalid")
    (repo / "README.md").write_text("Scaffold\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "Initial scaffold")
    git(repo, "push", "origin", "main")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "synthetic.jsonl").write_text(
        '{"id":"syn-0001","body":"Fictional prose."}\n'
    )
    (generated / "smoke_ids.txt").write_text("syn-0001\n")
    (generated / "faults.jsonl").write_text(
        '{"id":"syn-0001","injected_faults":["C8"]}\n'
    )
    return repo, remote, generated


def publish(repo: Path, generated: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(generated)], cwd=repo, capture_output=True, text=True
    )


def test_orphan_branch_and_clean_public_tree(
    repositories: tuple[Path, Path, Path],
) -> None:
    repo, remote, generated = repositories
    before = git(repo, "rev-parse", "HEAD")
    result = publish(repo, generated)
    assert result.returncode == 0, result.stderr
    assert git(repo, "rev-parse", "HEAD") == before
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "faults.jsonl").exists()
    paths = git(remote, "ls-tree", "-r", "--name-only", "main").splitlines()
    assert paths == ["README.md", "data/golden/synthetic.jsonl", "data/smoke_ids.txt"]
    assert git(remote, "ls-tree", "-r", "--name-only", "faults") == "faults.jsonl"
    assert git(remote, "rev-list", "--parents", "faults").count(" ") == 0
    main_content = git(remote, "show", "main:data/golden/synthetic.jsonl")
    assert "injected_faults" not in main_content
    first_faults = git(remote, "rev-parse", "faults")
    (generated / "faults.jsonl").write_text(
        '{"id":"syn-0001","injected_faults":["C9"]}\n'
    )
    result = publish(repo, generated)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "faults^") == first_faults
    assert git(remote, "rev-list", "--count", "faults") == "2"
    merged = subprocess.run(
        ["git", "-C", str(remote), "merge-base", "main", "faults"], capture_output=True
    )
    assert merged.returncode == 1


def test_atomic_rejection_keeps_both_refs_unchanged(
    repositories: tuple[Path, Path, Path],
) -> None:
    repo, remote, generated = repositories
    before = git(remote, "rev-parse", "main")
    hook = remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    result = publish(repo, generated)
    assert result.returncode != 0
    assert git(remote, "rev-parse", "main") == before
    missing = subprocess.run(
        ["git", "-C", str(remote), "show-ref", "--verify", "refs/heads/faults"],
        capture_output=True,
    )
    assert missing.returncode == 128


def test_refuses_fault_branch_with_main_ancestry(
    repositories: tuple[Path, Path, Path],
) -> None:
    repo, remote, generated = repositories
    git(repo, "push", "origin", "main:refs/heads/faults")
    before = git(remote, "rev-parse", "main")
    result = publish(repo, generated)
    assert result.returncode != 0
    assert "independent orphan history" in result.stderr
    assert git(remote, "rev-parse", "main") == before


@pytest.mark.parametrize(
    "metadata", ['"human":{"verdict":"READY"}', '"injected_faults":[]']
)
def test_refuses_to_replace_labeled_or_reconciled_data(
    repositories: tuple[Path, Path, Path],
    metadata: str,
) -> None:
    repo, remote, generated = repositories
    existing = repo / "data/golden/synthetic.jsonl"
    existing.parent.mkdir(parents=True)
    existing.write_text('{"id":"syn-0001",' + metadata + "}\n")
    git(repo, "add", "data/golden/synthetic.jsonl")
    git(repo, "commit", "-m", "Preserve completed labels")
    git(repo, "push", "origin", "main")
    before = git(remote, "rev-parse", "main")
    result = publish(repo, generated)
    assert result.returncode != 0
    assert "Refusing publication" in result.stderr
    assert git(remote, "rev-parse", "main") == before
    absent = subprocess.run(
        ["git", "-C", str(remote), "show-ref", "--verify", "refs/heads/faults"],
        capture_output=True,
    )
    assert absent.returncode == 128
