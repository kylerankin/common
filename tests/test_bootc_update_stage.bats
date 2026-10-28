#!/usr/bin/env bats
# Regression tests for projectbluefin/common#1417: the privileged
# bootc-update-stage helper treated a composefs "already up to date" refusal
# as a failure. On composefs (e.g. Dakota) `bootc upgrade` exits non-zero when
# the newest image is already booted or staged; the helper must treat only
# that refusal as success and keep any other failure's exit code.
#
# The helper invokes bootc by absolute path (/usr/bin/bootc) so the tests
# redirect that path into a sandbox stub, mirroring
# tests/test_clean_system_bootc.bats, and run the helper with a self-contained
# PATH so no host bootc can leak in.

STAGE_SCRIPT="${BATS_TEST_DIRNAME}/../system_files/shared/usr/libexec/bootc-update-stage"
WORKDIR=""

_setup() {
    WORKDIR="$(mktemp -d)"
    mkdir -p "${WORKDIR}/bin"
    : > "${WORKDIR}/calls.log"
    # Redirect the helper's absolute /usr/bin/bootc into the sandbox stub.
    sed "s#/usr/bin/bootc#${WORKDIR}/bin/bootc#g" "${STAGE_SCRIPT}" \
        > "${WORKDIR}/stage.sh"
    chmod +x "${WORKDIR}/stage.sh"
    # The helper runs under `#!/usr/bin/env bash` and calls grep by name;
    # keep the sandbox self-contained by symlink-only the tools it needs
    # (bootc itself is reached by the redirected absolute path, so no host
    # bootc can leak in).
    for tool in bash grep; do
        ln -s "$(command -v ${tool})" "${WORKDIR}/bin/${tool}"
    done
}

# Install a mock bootc. MOCK_BOOTC_EXIT is the exit code it returns for every
# invocation; MOCK_BOOTC_MSG (if non-empty) is printed to stderr first, so a
# non-zero exit can carry the composefs refusal text or a different error.
_install_mock_bootc() {
    local exit_code="$1" msg="${2:-}"
    {
        echo '#!/usr/bin/bash'
        printf 'printf "%%s\\n" "$*" >> "${STAGE_CALLS}"\n'
        echo 'if [ "${MOCK_BOOTC_EXIT}" -ne 0 ] && [ -n "${MOCK_BOOTC_MSG:-}" ]; then'
        printf '    printf "%%s\\n" "%s" >&2\n' "${msg}"
        echo 'fi'
        echo 'exit "${MOCK_BOOTC_EXIT}"'
    } > "${WORKDIR}/bin/bootc"
    chmod +x "${WORKDIR}/bin/bootc"
}

setup() {
    _setup
}

teardown() {
    rm -rf "${WORKDIR}"
}

# The composefs refusal, for an already-booted target (the #1417 headline case).
UP_TO_DATE_BOOTED='error: Upgrading composefs: Performing Upgrade Operation: Target image has the same fs-verity digest as the existing Some(Booted) deployment.'

# The same refusal when the newest image is already staged.
UP_TO_DATE_STAGED='error: Upgrading composefs: Performing Upgrade Operation: Target image has the same fs-verity digest as the existing Some(Staged) deployment.'

# A real failure that must still be reported, not swallowed.
REAL_ERROR='error: failed to pull and update: connection refused'

@test "bootc-update-stage: already-booted composefs refusal exits 0" {
    _install_mock_bootc 1 "${UP_TO_DATE_BOOTED}"
    run env STAGE_CALLS="${WORKDIR}/calls.log" \
        MOCK_BOOTC_EXIT=1 MOCK_BOOTC_MSG="${UP_TO_DATE_BOOTED}" \
        PATH="${WORKDIR}/bin" "${WORKDIR}/stage.sh"
    [ "${status}" -eq 0 ]
    grep -qFx "System image is already up to date." <<<"${output}"
}

@test "bootc-update-stage: already-staged composefs refusal exits 0" {
    _install_mock_bootc 1 "${UP_TO_DATE_STAGED}"
    run env STAGE_CALLS="${WORKDIR}/calls.log" \
        MOCK_BOOTC_EXIT=1 MOCK_BOOTC_MSG="${UP_TO_DATE_STAGED}" \
        PATH="${WORKDIR}/bin" "${WORKDIR}/stage.sh"
    [ "${status}" -eq 0 ]
    grep -qFx "System image is already up to date." <<<"${output}"
}

@test "bootc-update-stage: a different error preserves its exit code" {
    # A distinctive code (not 0/1) proves the helper forwards bootc's real
    # exit status instead of collapsing every failure to `exit 1`.
    _install_mock_bootc 42 "${REAL_ERROR}"
    run env STAGE_CALLS="${WORKDIR}/calls.log" \
        MOCK_BOOTC_EXIT=42 MOCK_BOOTC_MSG="${REAL_ERROR}" \
        PATH="${WORKDIR}/bin" "${WORKDIR}/stage.sh"
    [ "${status}" -eq 42 ]
}

@test "bootc-update-stage: a successful update exits 0" {
    _install_mock_bootc 0
    run env STAGE_CALLS="${WORKDIR}/calls.log" \
        MOCK_BOOTC_EXIT=0 \
        PATH="${WORKDIR}/bin" "${WORKDIR}/stage.sh"
    [ "${status}" -eq 0 ]
    # The read-only re-check must never run on a healthy upgrade.
    ! grep -q "upgrade --check" "${WORKDIR}/calls.log"
}
