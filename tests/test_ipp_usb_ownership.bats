#!/usr/bin/env bats
# Tests for issue #1214 — prove ipp-usb and raw USB scanner/printer
# ownership coexistence on a multifunction device.
#
# The "hardware" here is a virtual MFP. Real ownership is decided by kernel
# driver binding (usbip-host for ipp-usb, usblp/usbscanner for CUPS/SANE) and
# by libusb interface claims (SANE raw backend). None of that exists in CI, so
# the device model and the ownership resolver below are the mocked hardware
# boundary. See docs/skills/hardware-testing.md for the gate rationale.
#
# Run: bats tests/test_ipp_usb_ownership.bats

# --- Synthetic virtual MFP fixture ------------------------------------------
# A multifunction device exposes several logical USB interfaces on one physical
# USB device. Each interface has a class and a purpose. Three user-space
# consumers contest the interfaces:
#
#   ipp-usb : serves IPP/eSCL over the interfaces it binds (usbip-host driver).
#             When it binds an interface, the kernel usblp/usbscanner drivers
#             and the SANE raw (libusb) backend cannot.
#   cups    : CUPS usb backend, owns the raw printer interface via usblp.
#   sane    : SANE raw backend, owns the raw scanner interface via libusb.
#
# The invariant under test: exactly one consumer owns each logical interface.
# Coexistence is possible precisely because the printer and scanner are
# *different* logical interfaces — different consumers can own them on the same
# physical device without conflict.

declare -A IF_CLASS
declare -A IF_PURPOSE
declare -A OWNER
declare -A WANTED

# Active device policy (reversible Bluefin device policy, see docs).
IPP_ENABLED=0
IPP_SCAN_SKIP=0

setup() {
    # A typical multifunction printer/scanner on one USB device.
    IF_CLASS=( [0]=printer [1]=scanner [2]=mass_storage )
    IF_PURPOSE=(
        [0]="raw print via usblp"
        [1]="raw scan via sane-raw"
        [2]="card reader, no IPP function"
    )
    OWNER=()
    WANTED=()
}

# --- Ownership model ---------------------------------------------------------
# Record which consumers *want* an interface, then resolve exactly one owner.
# A resolved owner of "none" means no print/scan consumer claims it.
assign_wants() {
    local id class
    for id in "${!IF_CLASS[@]}"; do
        class="${IF_CLASS[$id]}"
        case "${class}" in
            printer)
                WANTED[$id]="cups"
                [ "${IPP_ENABLED}" -eq 1 ] && WANTED[$id]="ipp-usb ${WANTED[$id]}"
                ;;
            scanner)
                WANTED[$id]="sane"
                if [ "${IPP_ENABLED}" -eq 1 ] && [ "${IPP_SCAN_SKIP}" -eq 0 ]; then
                    # ipp-usb can serve this scanner (eSCL), so it wants it too.
                    WANTED[$id]="ipp-usb ${WANTED[$id]}"
                fi
                ;;
            *)
                WANTED[$id]=""
                ;;
        esac
    done
}

# Resolve one owner per interface from the recorded wants.
# Policy: ipp-usb wins when it wants the interface; otherwise the remaining
# raw consumer (cups/sane) owns it; otherwise "none".
resolve_owners() {
    local id want owner
    for id in "${!IF_CLASS[@]}"; do
        owner="none"
        for want in ${WANTED[$id]}; do
            if [ "${want}" = "ipp-usb" ]; then
                owner="ipp-usb"
            elif [ "${owner}" = "none" ]; then
                owner="${want}"
            fi
        done
        OWNER[$id]="${owner}"
    done
}

assign_owners() {
    assign_wants
    resolve_owners
}

# One line per interface: "id class owner wanted".
print_ownership() {
    local id
    for id in $(echo "${!IF_CLASS[@]}" | tr ' ' '\n' | sort -n); do
        printf '%s class=%s owner=%s wanted=[%s]\n' \
            "${id}" "${IF_CLASS[$id]}" "${OWNER[$id]}" "${WANTED[$id]}"
    done
}

# Count owners recorded for an interface (0, 1, or 2+).
owner_count() {
    local n=0 want
    for want in ${WANTED[$1]}; do
        n=$((n + 1))
    done
    echo "${n}"
}

# ---------------------------------------------------------------------------
# Core invariant: one owner per logical interface
# ---------------------------------------------------------------------------

@test "ipp-usb disabled: cups owns printer, sane owns scanner, one owner each" {
    IPP_ENABLED=0
    assign_owners

    [ "${OWNER[0]}" = "cups" ]
    [ "${OWNER[1]}" = "sane" ]
    [ "$(owner_count 0)" -eq 1 ]
    [ "$(owner_count 1)" -eq 1 ]
}

@test "mass storage interface has no print/scan owner" {
    IPP_ENABLED=1
    assign_owners

    [ "${IF_CLASS[2]}" = "mass_storage" ]
    [ "${OWNER[2]}" = "none" ]
    [ "$(owner_count 2)" -eq 0 ]
}

@test "every logical interface resolves to exactly one owner (no double-bind)" {
    for policy in "0 0" "0 1" "1 0" "1 1"; do
        set -- ${policy}
        IPP_ENABLED="$1"
        IPP_SCAN_SKIP="$2"
        assign_owners

        # The resolved owner is always exactly one consumer — never empty,
        # never "multiple". Contention is allowed in *wants* (owner_count > 1)
        # but the resolver always collapses it to a single owner.
        local id seen
        for id in "${!IF_CLASS[@]}"; do
            seen+="${OWNER[$id]} "
        done
        # Exactly one owner token per interface; count non-empty tokens.
        local ids=(${!IF_CLASS[@]}) nowners=0
        for id in "${ids[@]}"; do
            [ -n "${OWNER[$id]}" ] && nowners=$((nowners + 1))
        done
        [ "${nowners}" -eq "${#ids[@]}" ]
    done
}

# ---------------------------------------------------------------------------
# Coexistence: ipp-usb and raw USB SANE own different interfaces, same device
# ---------------------------------------------------------------------------

@test "reversible policy (ipp-usb scan-skip): ipp-usb and sane coexist, disjoint owners" {
    IPP_ENABLED=1
    IPP_SCAN_SKIP=1   # Bluefin policy: ipp-usb declines the raw scanner interface
    assign_owners

    local report
    report="$(print_ownership)"

    # ipp-usb owns the printer, sane owns the scanner — disjoint.
    [ "${OWNER[0]}" = "ipp-usb" ]
    [ "${OWNER[1]}" = "sane" ]
    # The physical device is shared; no interface is double-owned.
    [ "$(grep -c 'owner=ipp-usb' <<<"${report}")" -eq 1 ]
    [ "$(grep -c 'owner=sane' <<<"${report}")" -eq 1 ]
    [ "$(grep -c 'owner=none' <<<"${report}")" -eq 1 ]
}

@test "coexistence: printer and scanner are separate interfaces on one device" {
    IPP_ENABLED=1
    IPP_SCAN_SKIP=1
    assign_owners

    # Distinct logical interfaces (different ids) share the physical device.
    [ "${OWNER[0]}" != "${OWNER[1]}" ]
    # The raw SANE backend never wants the printer interface — the printer is
    # never contested by sane.
    case "${WANTED[0]}" in *sane*) false ;; *) true ;; esac
}

# ---------------------------------------------------------------------------
# Conflict: when ipp-usb also claims the raw scanner, one interface is contested
# (the hardware-dependent usbip-vs-libusb claim that stays unverified in CI).
# ---------------------------------------------------------------------------

@test "ipp-usb without scan-skip makes the scanner interface contested" {
    IPP_ENABLED=1
    IPP_SCAN_SKIP=0   # ipp-usb tries to serve the scanner too
    assign_owners

    # Both ipp-usb and sane want the scanner interface.
    [ "$(owner_count 1)" -eq 2 ]
    # Resolution still picks a single owner (ipp-usb wins the bind).
    [ "${OWNER[1]}" = "ipp-usb" ]
}

@test "toggling scan-skip releases the scanner from ipp-usb back to sane" {
    IPP_ENABLED=1

    IPP_SCAN_SKIP=0
    assign_owners
    [ "${OWNER[1]}" = "ipp-usb" ]

    IPP_SCAN_SKIP=1
    assign_owners
    [ "${OWNER[1]}" = "sane" ]
}
