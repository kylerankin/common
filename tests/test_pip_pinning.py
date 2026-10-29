"""Tests for scripts/check-pip-pinned.py.

The checker fails a pull request when a workflow installs a Python tool
without pinning every package to an exact version. We test the argument
parsing directly and run the checker end to end against a temporary
workflows directory.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "scripts"
CHECK_PIP_PINNED = SCRIPTS / "check-pip-pinned.py"

spec = importlib.util.spec_from_file_location("check_pip_pinned", CHECK_PIP_PINNED)
check_pip_pinned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_pip_pinned)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("pip install pytest pytest-cov", ["pytest", "pytest-cov"]),
        ("pip install pre-commit", ["pre-commit"]),
        ("pip install pytest==9.2.0 pytest-cov==7.1.0", []),
        ("pip install pre-commit==4.7.0", []),
        ("pip install --upgrade pytest==8.3.4", []),
        ("pip3 install -r requirements.txt", []),
        ("python -m pip install requests>=2.0", ["requests>=2.0"]),
        ('python3 -m pip install "requests==2.32.2"', []),
        ("pip install pkg[extra]==1.0", []),
        ("pip install unpinned pinned==1.0", ["unpinned"]),
    ],
)
def test_unpinned_in(command, expected):
    assert check_pip_pinned.unpinned_in(command) == expected


def test_logical_lines_join_continuations():
    text = "pip install \\\n    numpy==1.26.0 \\\n    pandas==2.2.0\n"
    lines = list(check_pip_pinned.logical_lines(text))
    assert len(lines) == 1
    lineno, joined = lines[0]
    assert lineno == 1
    assert "numpy==1.26.0" in joined
    assert "pandas==2.2.0" in joined
    assert check_pip_pinned.unpinned_in(joined) == []


def test_check_against_temp_workflows(tmp_path, monkeypatch):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "good.yml").write_text(
        "run: pip install pytest==9.2.0 pytest-cov==7.1.0\n",
        encoding="utf-8",
    )
    (workflows / "bad.yml").write_text(
        "run: pip install requests\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_pip_pinned, "WORKFLOWS_DIR", workflows)

    errors = check_pip_pinned.check()
    assert len(errors) == 1
    assert "bad.yml:1: unpinned pip install: requests" in errors[0]

    assert check_pip_pinned.main() == 1
    assert "bad.yml:1: unpinned pip install: requests" in errors


def test_check_clean_workflows(tmp_path, monkeypatch):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "a.yml").write_text(
        "run: pip install pre-commit==4.7.0\n",
        encoding="utf-8",
    )
    (workflows / "b.yaml").write_text(
        "run: python -m pip install pytest==8.3.4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_pip_pinned, "WORKFLOWS_DIR", workflows)

    assert check_pip_pinned.check() == []
    assert check_pip_pinned.main() == 0


def test_main_returns_zero_when_no_workflows_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(check_pip_pinned, "WORKFLOWS_DIR", tmp_path / "absent")
    assert check_pip_pinned.check() == []
    assert check_pip_pinned.main() == 0
