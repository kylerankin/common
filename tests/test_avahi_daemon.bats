#!/usr/bin/env bats
# Tests for the avahi-daemon.service drop-in that fixes common#1327
# (mDNS name resolution fails on Utah).
#
# Run: bats tests/test_avahi_daemon.bats

UNIT_DIR="$BATS_TEST_DIRNAME/../system_files/shared/usr/lib/systemd/system/avahi-daemon.service.d"
UNIT="${UNIT_DIR}/10-bluefin.conf"

setup() {
    [ -f "${UNIT}" ] || skip "drop-in ${UNIT} not present"
}

# Active (non-comment) config lines of the drop-in.
active() { grep -v '^[[:space:]]*#' "${UNIT}"; }

@test "avahi: drop-in declares the RuntimeDirectory" {
    active | grep -q '^RuntimeDirectory=avahi-daemon$'
}

@test "avahi: runtime directory is owned by the avahi user the daemon drops to" {
    # The stock service runs as root and drops privileges itself (no User=), so
    # systemd would otherwise chown /run/avahi-daemon to root. Pin it to avahi,
    # the user the daemon actually switches to, or the pid file write still fails
    # with "Permission denied" (common#1327).
    active | grep -q '^RuntimeDirectoryUser=avahi$'
    active | grep -q '^RuntimeDirectoryGroup=avahi$'
}

@test "avahi: runtime directory mode lets avahi write its pid file" {
    # 0755 avahi:avahi — owner avahi can create the pid file, matching the mode
    # the stock avahi.conf tmpfiles entry uses.
    active | grep -q '^RuntimeDirectoryMode=0755$'
}

@test "avahi: drop-in is named for and references the avahi-daemon.service unit" {
    [ "$(basename "${UNIT}")" = "10-bluefin.conf" ]
    grep -q 'avahi-daemon' "${UNIT}"
}

@test "avahi: drop-in only touches the [Service] section" {
    # A drop-in for the running daemon must not redeclare [Unit]/[Install]; the
    # runtime directory is a [Service] property.
    [ "$(active | grep -cE '^\[.*\]$')" -eq 1 ]
    active | grep -q '^\[Service\]$'
}

@test "avahi: drop-in passes systemd-analyze verify" {
    command -v systemd-analyze >/dev/null 2>&1 || skip "systemd-analyze not available"
    # A drop-in is not a loadable unit on its own, so validate it against a
    # synthetic root that also carries a minimal stock avahi-daemon.service;
    # systemd-analyze merges the .d drop-in when it verifies the unit.
    local root="${BATS_TEST_TMPDIR}/avahi-root"
    local sys="${root}/usr/lib/systemd/system"
    local din="${sys}/avahi-daemon.service.d"
    mkdir -p "${din}"
    cat > "${sys}/avahi-daemon.service" <<'EOF'
[Unit]
Description=Avahi mDNS/DNS-SD Stack

[Service]
Type=simple
ExecStart=/usr/sbin/avahi-daemon -s
Restart=on-failure
EOF
    cp "${UNIT}" "${din}/10-bluefin.conf"
    run systemd-analyze verify --root="${root}" "${sys}/avahi-daemon.service"
    [ "${status}" -eq 0 ]
}
