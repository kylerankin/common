"""Tests for Project Bluefin GitHub Actions Security Baseline conformance."""

import subprocess
import sys
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts/check-actions-security.py"
WORKFLOWS_DIR = ROOT / ".github/workflows"
DOC = ROOT / "ACTIONS-SECURITY.md"


def test_repo_workflows_conform_to_security_baseline():
    """All repository workflows in .github/workflows must pass the security baseline check."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--workflows-dir", str(WORKFLOWS_DIR), "--strict"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Baseline check failed:\n{result.stdout}\n{result.stderr}"
    assert "0 error(s)" in result.stdout


def test_actions_security_doc_exists_and_covers_required_pillars():
    """ACTIONS-SECURITY.md must exist and document the four core pillars."""
    assert DOC.exists(), "ACTIONS-SECURITY.md must exist at repo root"
    content = DOC.read_text(encoding="utf-8")

    # Pillar 1: top-level permissions: {}
    assert "permissions: {}" in content
    assert "Pillar 1" in content or "permissions" in content.lower()

    # Pillar 2: SHA pinning
    assert "40-character" in content or "commit SHA" in content
    assert "Pillar 2" in content or "pinning" in content.lower()

    # Pillar 3: pull_request_target
    assert "pull_request_target" in content
    assert "Pillar 3" in content or "pull_request_target" in content

    # Pillar 4: release-asset checksum verification
    assert "SHA-256" in content or "checksum" in content.lower()
    assert "Pillar 4" in content or "checksum" in content.lower()


def test_scanner_detects_missing_top_level_permissions(tmp_path: Path):
    """The scanner must flag workflows that lack top-level permissions."""
    wf = tmp_path / "bad-permissions.yml"
    wf.write_text("""
name: Test Workflow
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: echo hello
""")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--workflows-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing top-level 'permissions:' declaration" in result.stdout


def test_scanner_detects_floating_action_tag(tmp_path: Path):
    """The scanner must flag external actions using floating tags."""
    wf = tmp_path / "floating-tag.yml"
    wf.write_text("""
name: Test Workflow
on: [push]
permissions: {}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--workflows-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must be pinned to a full 40-character commit SHA" in result.stdout


def test_scanner_detects_dangerous_pr_target_checkout(tmp_path: Path):
    """The scanner must flag untrusted PR head checkouts in pull_request_target."""
    wf = tmp_path / "dangerous-pr-target.yml"
    wf.write_text("""
name: PR Target Workflow
on: pull_request_target
permissions: {}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          ref: ${{ github.event.pull_request.head.sha }}
""")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--workflows-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Dangerous untrusted PR checkout detected" in result.stdout


@pytest.mark.parametrize(
    "ref_expression",
    [
        "${{ github.head_ref }}",
        "${{ github.event.pull_request.head.ref }}",
        "${{ github.event.pull_request.head.sha }}",
        "${{ github.event.pull_request.head.repo.full_name }}",
    ],
)
def test_scanner_detects_all_untrusted_pr_head_expressions(tmp_path: Path, ref_expression: str):
    """Every untrusted PR-head expression must be flagged, including github.head_ref."""
    wf = tmp_path / "pwn-request.yml"
    wf.write_text(f"""
name: PR Target Workflow
on: pull_request_target
permissions: {{}}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          ref: {ref_expression}
""")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--workflows-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Dangerous untrusted PR checkout detected" in result.stdout


def test_scanner_allows_head_ref_outside_pr_target(tmp_path: Path):
    """github.head_ref in a plain pull_request workflow is not a privileged-context risk."""
    wf = tmp_path / "plain-pr.yml"
    wf.write_text("""
name: PR Workflow
on: pull_request
permissions: {}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          ref: ${{ github.head_ref }}
""")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--workflows-dir", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "permissions_block",
    [
        "permissions: write-all",
        "permissions:\n  contents: write",
        "permissions:\n  contents: read\n  packages: write\n  id-token: write",
    ],
)
def test_scanner_detects_forbidden_top_level_write_permissions(tmp_path: Path, permissions_block: str):
    """The scanner must flag top-level write-all or write scope permissions."""
    wf = tmp_path / "write-scope.yml"
    wf.write_text(f"""
name: Write Scope Workflow
on: [push]
{permissions_block}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo hello
""")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--workflows-dir", str(tmp_path), "--strict"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "forbidden" in result.stdout.lower() or "violates" in result.stdout.lower()


def _load_fallback_module():
    """Import the scanner as a module so the fallback parser can be exercised."""
    spec = importlib.util.spec_from_file_location(
        "check_actions_security_fallback", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "workflow",
    [
        # scalar trigger
        "on: pull_request_target\njobs:\n  j:\n    runs-on: x\n",
        # inline flow list
        "on: [push, pull_request_target]\njobs:\n  j:\n    runs-on: x\n",
        # multi-line flow list -- the gap reported in #1436
        "on: [push,\n  pull_request_target]\njobs:\n  j:\n    runs-on: x\n",
        # block sequence
        "on:\n  - push\n  - pull_request_target\njobs:\n  j:\n    runs-on: x\n",
        # quoted on: key with mapping trigger
        '"on":\n  pull_request_target:\n    types: [opened]\njobs:\n  j:\n    runs-on: x\n',
        "'on':\n  pull_request_target:\n    types: [opened]\njobs:\n  j:\n    runs-on: x\n",
    ],
)
def test_fallback_parser_detects_pr_target_triggers(workflow: str):
    """With PyYAML absent the fallback parser must flag pull_request_target whether
    it appears as a scalar, inline flow list, multi-line flow list, or block list."""
    module = _load_fallback_module()
    module.yaml = None  # force the fallback (non-PyYAML) parser
    assert module._has_pr_target_in_on(workflow.splitlines()) is True


@pytest.mark.parametrize(
    "workflow",
    [
        "on: [push, pull_request]\njobs:\n  j:\n    runs-on: x\n",
        "on: [push,\n  pull_request]\njobs:\n  j:\n    runs-on: x\n",
        "on:\n  - push\n  - pull_request\njobs:\n  j:\n    runs-on: x\n",
        "jobs:\n  j:\n    runs-on: x\n    steps:\n      - uses: a/b@v1 # pull_request_target\n",
        # token only in a comment inside the on: block
        "on:\n  pull_request:  # not pull_request_target\njobs:\n  j:\n    runs-on: x\n",
        "on:\n  # pull_request_target\n  - push\njobs:\n  j:\n    runs-on: x\n",
    ],
)
def test_fallback_parser_allows_non_pr_target(workflow: str):
    """The fallback parser must not flag pull_request, and must ignore the token in
    comments or out of the on: context."""
    module = _load_fallback_module()
    module.yaml = None
    assert module._has_pr_target_in_on(workflow.splitlines()) is False


def test_fallback_multiline_flow_list_flags_untrusted_checkout(tmp_path: Path):
    """End-to-end: a multi-line flow-list on: with pull_request_target plus an
    untrusted checkout must be flagged even when PyYAML is absent."""
    module = _load_fallback_module()
    module.yaml = None
    wf = tmp_path / "dangerous-multiline.yml"
    wf.write_text("""
name: PR Target Workflow
on: [push,
  pull_request_target]
permissions: {}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          ref: ${{ github.head_ref }}
""")
    issues = module.check_workflow_file(wf)
    messages = "\n".join(str(i) for i in issues)
    assert "Dangerous untrusted PR checkout detected" in messages, messages


def test_fallback_multiline_flow_list_without_pr_target_allows_checkout(tmp_path: Path):
    """A multi-line flow list that only lists pull_request must not be treated as a
    privileged context, so a head_ref checkout stays allowed."""
    module = _load_fallback_module()
    module.yaml = None
    wf = tmp_path / "plain-multiline.yml"
    wf.write_text("""
name: PR Workflow
on: [push,
  pull_request]
permissions: {}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7
        with:
          ref: ${{ github.head_ref }}
""")
    issues = module.check_workflow_file(wf)
    messages = "\n".join(str(i) for i in issues)
    assert "Dangerous untrusted PR checkout detected" not in messages, messages
