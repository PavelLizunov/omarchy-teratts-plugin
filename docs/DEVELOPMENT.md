# Development and verification

This repository is the public installable TeraTTS source package. Omarchy loads a
separate directory under ~/.config/omarchy/plugins/io.github.pavellizunov.teratts.
Saving this checkout does not install it. Use the installed host's native controls
and retain Read / Files / Settings, the fixed footer and selected larger A mark.

## Checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -q
python3 -B tools/check-publication.py
omarchy plugin validate .
python3 -B tests/capture_ui.py --output /tmp/teratts-ui-check
python3 -B tests/capture_ui.py --prepare-preview --output /tmp/teratts-preview-check
python3 -B tests/install_native.py
python3 -B tests/capture_demo.py --output /tmp/teratts-demo-check
```

Python tests use isolated XDG stores, synthetic loopback servers, inert keyring/
clipboard/capture tools and a real null-output mpv. CI treats unexpected skips as
failure. Public setup checks reject missing endpoints before network and route
export to two user-configured server fixtures. They do not verify remote accounts.

The QML harness loads the actual Panel.qml and installed controls; only processes,
I/O catalogs and surfaces are made inert. Separate strict offscreen renders use
explicit imports, readiness, locale, density and dependency hashes. QtQuick 6.11
imports preserve the host Color singleton contract when running on Qt 6.12.
No second live Quickshell, desktop capture or input injection is required.

## Public content boundary

The public repository starts with a clean source snapshot. Dated private machine
reports, account/session metadata, raw logs, .dsh workspaces and personal endpoint
addresses are not included. tools/check-publication.py counts all tracked files
and reachable Git blobs, tests its detectors, rejects symlinks/private-artifact
paths and checks manifest/docs/runtime requirements. Pattern checks are bounded
controls, not universal secret or security certification. The synthetic base64
sanitizer fixture is an explicit known test, not a stored bearer token.

## Current evidence and limits

The underlying 0.3.16 panel/backend was checked with 162 Python tests, 28 actual
Qt results and seven installed CLI scenarios. Public 0.3.17 changes the default
setup and sample assets. Its local checks passed 157 Python tests, 28 Qt results,
two public/native-package checks and four inspected strict native renders.
The 54-frame silent demo passed capture and encoded-frame checks. Its own
exact-head Python and publication results are recorded in CI. The public package
was not deployed over the maintainer's running private 0.3.16 installation.
Source, rendered, installed, loaded and physically tested states remain separate.

Whole-plugin qmllint exits zero on the available host, but reports unresolved
qs.Commons/qs.Ui imports and derived type warnings. This is not a clean lint pass;
actual native-control coverage comes from the offscreen consumer harness.
Compositor placement and a new live enable/disable/restart cycle remain untested.

Preview images and video use inert data, not a functioning remote server or
measured audio quality. The selected icon and measured playback algorithm remain.
Live theme switching, compositor placement, multimonitor hotplug, screen readers,
physical global keys, hearing/pronunciation and optional privileged setup/rollback
are not universally verified. A user-reported clipped left frame received native
inner clearance; software rendering did not reproduce the exact GPU pixel loss.

Native add/remove commands were source-reviewed and tested against a disposable
HOME with an inert shell IPC boundary. Real user settings and recordings are not
used for these tests. Adding/removing plugins may reload shared shell surfaces;
preserve current work. Marketplace validation checks listing compatibility, not
plugin security or maintainer approval.
