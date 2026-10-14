# Security and data disclosure

Report vulnerabilities privately through GitHub's repository security reporting
when available; otherwise contact the maintainer without posting credentials or
private captured text. This is a community plugin, not a sandboxed application.
Its QML runs with user permissions inside Omarchy's shared shell. Listing approval
is not a security review.

Text is sent only to the user-selected TeraTTS-compatible endpoint. There is no
default service or bundled account. Captured images go to the selected OCR engine;
cloud/remote OCR requires sending them externally. Local OCR stays local. Tokens
are resolved from environment or keyring. Do not place a token in a URL or commit
configuration, captures or recordings.

The synthesis path validates endpoint schemes, rejects redirects, bounds inputs
and audio payloads, owns cancellation and preserves existing export files on
quota failure. Playback and optional dependencies remain upstream software with
their own attack surfaces; these controls do not certify arbitrary servers or
binaries. Optional recognition setup downloads pinned packages/models explicitly.

Native plugin installation/removal does not install shortcuts or erase user data.
Shortcut setup edits only its owned block when explicitly invoked. Package removal
should follow Stop and owned-binding removal. Do not use an untrusted plugin
repository or enable this package together with its predecessor.
