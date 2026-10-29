#!/usr/bin/env python3
"""Fail a pull request when a workflow installs an unpinned Python tool.

The pull-request checks install a few Python tools with ``pip install``. A bare
``pip install pytest`` resolves to whatever is newest on the index at run time,
so a check can start behaving differently with no change to the workflow. Every
package a check installs is pinned to an exact version (``name==version``) so
runs are reproducible.

This scans every YAML file under ``.github/`` and fails when a ``pip
install`` line contains a package that is not pinned with ``==``. It is wired up
as the ``no-unpinned-pip-tools`` pre-commit hook, so it runs inside the
existing "Run pre-commit" step of the Validate PR workflow.
"""

import re
import sys
from pathlib import Path

WORKFLOWS_DIR = Path(".github")

# A pip install command: `pip`, `pip3`, `python -m pip`, or `python3 -m pip`.
PIP_INSTALL_RE = re.compile(r"(?:^|\s)(?:pip3?|python3?\s+-m\s+pip)\s+install\b")

# A requirement argument pinned to an exact version: name[extras]==version.
PINNED_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[^\]]*\])?==")

# Flags whose next token is a file/path, not a package to pin.
SKIPS_VALUE = {
    "-r",
    "--requirement",
    "-c",
    "--constraint",
    "-t",
    "--target",
    "-e",
    "--editable",
    "-i",
    "--index-url",
    "--extra-index-url",
    "--find-links",
}


def logical_lines(text):
    """Yield ``(line_number, joined_text)`` joining backslash continuations."""
    buf = ""
    start = 0
    for idx, line in enumerate(text.splitlines(), start=1):
        if not buf:
            start = idx
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
        else:
            buf += line
            yield start, buf
            buf = ""
    if buf:
        yield start, buf


def unpinned_in(command):
    """Return the unpinned requirement arguments in a pip install command."""
    rest = command.split("install", 1)[1]
    tokens = rest.split()
    found = []
    skip_next = False
    for arg in tokens:
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            break
        if arg.startswith("-"):
            skip_next = arg in SKIPS_VALUE
            continue
        arg = arg.strip("'\"")
        if not PINNED_RE.match(arg):
            found.append(arg)
    return found


def check():
    """Return a list of human-readable error strings for every unpinned install."""
    errors = []
    if not WORKFLOWS_DIR.exists():
        return errors
    files = sorted(WORKFLOWS_DIR.rglob("*.yml")) + sorted(
        WORKFLOWS_DIR.rglob("*.yaml"),
    )
    for wf in files:
        text = wf.read_text(encoding="utf-8")
        for lineno, line in logical_lines(text):
            if not PIP_INSTALL_RE.search(line):
                continue
            bad = unpinned_in(line)
            for pkg in bad:
                errors.append(f"{wf.name}:{lineno}: unpinned pip install: {pkg}")
    return errors


def main():
    errors = check()
    for message in errors:
        print(f"error: {message}")
    if errors:
        print(
            f"\n{len(errors)} unpinned pip install(s) found. "
            "Pin every package with == so pull-request checks are reproducible.",
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
