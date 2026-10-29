# Pinning pip-installed Python tools

Part of [ci-tooling](../SKILL.md) — the policy that every Python tool a
pull-request check installs is pinned to an exact version, and the
`no-unpinned-pip-tools` pre-commit hook that enforces it.

---

## The policy

**Every Python tool a pull-request check installs must be pinned to an exact
version with `==`.** A bare `pip install pytest` resolves to whatever is newest
on the index at run time, so a check can start behaving differently — a passing
test suite turns red, or a new error appears — with no change to the workflow.
Pin every package (`name==version`) so runs are reproducible.

```yaml
# correct — every package pinned
- name: Install deps
  run: pip install pytest==9.2.0 pytest-cov==7.1.0 pyyaml==6.0.3

# rejected by the no-unpinned-pip-tools hook
- name: Install deps
  run: pip install pytest pytest-cov pyyaml
```

## Why

- **Reproducibility.** An unpinned install silently changes over time; a pin
  makes a green build mean the same thing next month.
- **Supply chain.** A pin is the dependency-side mirror of the SHA-pinning
  policy in [sha-pinning.md](sha-pinning.md): it removes a moving target that a
  compromised or repurposed package could exploit.
- **Fast, cheap failures.** The check reads the workflow text and reports the
  offending file, line, and package — no install, no network, no flakiness.

## The pattern

```yaml
# pip / pip3 / python -m pip — all forms are checked
run: pip install pre-commit==4.7.0
run: python3 -m pip install numpy==2.5.4

# requirements/constraint files are allowed and must not be pinned inline
run: pip install -r requirements.txt
run: pip install --constraint constraints.txt

# a package may carry extras; it still needs ==
run: pip install "requests[security]==2.32.3"
```

## The check

`scripts/check-pip-pinned.py` scans every YAML file under `.github/` and fails
when a `pip install` line contains a package that is not pinned with `==`.

- It understands `pip`, `pip3`, `python -m pip`, and `python3 -m pip`.
- It skips the value-taking flags `-r`, `-c`, `-t`, `-e`, `-i`,
  `--requirement`, `--constraint`, `--target`, `--editable`, `--index-url`,
  `--extra-index-url`, and `--find-links`, so pinned requirement files are not
  flagged.
- It joins backslash line continuations, strips quotes, and stops at `--`.
- It reports `filename:line: unpinned pip install: <package>`.

The hook is registered in `.pre-commit-config.yaml` as `no-unpinned-pip-tools`
(`language: system`, `always_run: true`, `pass_filenames: false`), so it runs
inside the existing "Run pre-commit" step of the Validate PR workflow and inside
`pre-commit` locally. It is wired the same way as `no-floating-action-tags`.

### If you add a new pip install

1. Pin every package in the workflow (`name==version`).
2. Run `pre-commit run no-unpinned-pip-tools --all-files` to confirm the hook
   is clean.
3. If you add a new install to a workflow that is NOT under `.github/`, note
   that the hook scans all of `.github/` — a pip install elsewhere (for example
   a composite action in `projectbluefin/actions`) is out of scope here and
   belongs in that repo's own guard.

## Tests

`tests/test_pip_pinning.py` covers the argument parsing (pinned vs unpinned,
extras, `-r`/`-c` skips, quoted packages, line continuations) and runs the
checker end to end against a temporary `.github/` tree. The suite is registered
in the Justfile `test` recipe, and `test_suite_registration.bats` enforces that
registration.

## Red Flags

- A workflow installs a tool with a bare `pip install pytest` and no `==`
- A new pip install is added under a path the hook does not scan, with no
  equivalent guard in that repo
- A requirement file is pinned inline instead of the packages it references
