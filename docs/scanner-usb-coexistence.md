# ipp-usb and raw USB scanner/printer ownership coexistence

> Issue: [projectbluefin/common#1214](https://github.com/projectbluefin/common/issues/1214)
> Parent epic: [projectbluefin/common#1210](https://github.com/projectbluefin/common/issues/1210)

How a single multifunction (MFP) USB device — printer **and** scanner on one
USB body — is owned without two user-space consumers fighting over the same
logical interface.

## The conflict

A multifunction device exposes several **logical USB interfaces** on one
physical USB device. Three consumers can claim them:

| Consumer | Path | Claims |
|----------|------|--------|
| `ipp-usb` | binds interfaces to the kernel `usbip-host` driver (via `configfs`) | serves IPP/eSCL over the interfaces it binds |
| `cups` (usb backend) | kernel `usblp` driver | raw printer interface |
| `sane` (raw backend) | `libusb` interface claim | raw scanner interface |

`ipp-usb` and the SANE raw backend are mutually exclusive **per interface**:
once `ipp-usb` binds an interface to `usbip-host`, the kernel `usbscanner`
driver does not bind it and `libusb` cannot claim it. So an interface has
exactly one owner — or the two consumers collide.

## The principle: one owner per logical interface

Coexistence is possible precisely because the printer and scanner are
**different logical interfaces**. The rule:

> Each logical USB interface on a device has exactly one owner. Different
> consumers may own different interfaces of the same physical device without
> conflict.

- Printer interface → owned by `ipp-usb` (IPP printing) **or** `cups` (usblp).
- Scanner interface → owned by `ipp-usb` (eSCL) **or** `sane` (raw).
- A `mass_storage` / card-reader interface has no print/scan owner.

When `ipp-usb` serves the printer but **declines** the scanner (the scanner has
no eSCL function, or the device policy says so), `ipp-usb` owns the printer and
`sane` owns the scanner on the same physical device — coexistence.

## Synthetic coverage

`tests/test_ipp_usb_ownership.bats` models a virtual MFP (three logical
interfaces) and an ownership resolver, and asserts:

- every logical interface resolves to exactly one owner (no double-bind);
- with the reversible policy (`ipp-usb` declines the scanner), `ipp-usb` and
  `sane` own disjoint interfaces on the same device;
- when `ipp-usb` also claims the scanner, that single interface is **contested**
  (`ipp-usb` + `sane` both want it) and the resolver still picks one owner.

The device model and resolver are the mocked hardware boundary — see
[`docs/skills/hardware-testing.md`](skills/hardware-testing.md). CI has no
`usbip` host binding and no real `libusb` interface claims, so this proves the
**ownership invariant**, not the kernel-level bind.

## Hardware effects: unverified

No physical scanner is available. The following remain **unverified** and must
be reported as such (per the issue scope):

- the actual `usbip-host` bind vs. `usblp`/`usbscanner` kernel race on a real
  MFP;
- whether a specific device's scanner exposes an eSCL function that `ipp-usb`
  will try to serve;
- SANE backend selection (`auto`/`airscan`/`raw`) once `ipp-usb` is running.

## Recommendation: a reversible Bluefin device policy

Ship a **reversible** policy knob rather than a hard-coded bind list, so a user
can restore raw scanner access without a reinstall:

1. `ipp-usb` is enabled by default for driverless printing/eSCL.
2. A documented toggle (e.g. an `ujust` choice or a drop-in config flag) lets a
   user tell `ipp-usb` to **skip** the scanner interface, releasing it to the
   SANE raw backend — the exact `IPP_SCAN_SKIP` branch exercised in the test.
3. Document the one-command rollback in the Bluefin docs so the change is
   reversible and auditable.

The toggle is intentionally coarse (per-device scan-skip), not a
per-interface ACL — that is the documented ceiling; widen it only if a real
device forces it.

## Evidence

- [OpenPrinting/ipp-usb](https://github.com/OpenPrinting/ipp-usb) — usbip-host
  binding model.
- [OpenPrinting/go-mfp](https://github.com/OpenPrinting/go-mfp) — virtual MFP
  fixture used by the sibling scanner-fixture issue [#1212](https://github.com/projectbluefin/common/issues/1212).
- [SANE backends](https://gitlab.com/sane-project/backends) — raw backend.
