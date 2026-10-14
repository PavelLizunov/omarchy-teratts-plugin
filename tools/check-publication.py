#!/usr/bin/env python3
"""Count and check the public package and reachable blobs; not universal clearance."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
RULES = (
    ("private-home", re.compile(rb"/home/(?!runner(?:/|\b)|user(?:/|\b))[A-Za-z0-9_-]+")),
    ("private-network", re.compile(rb"[A-Za-z0-9_.-]+\.ts\.net")),
    ("private-artifact", re.compile(rb"(?:" + rb"\.d" + rb"sh/|nin" + rb"itux/|session[_-]?(?:id|file)\s*[:=]\s*[\"'][A-Za-z0-9_-]{8})", re.I)),
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY")),
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("cloud-token", re.compile(rb"\bAKIA[0-9A-Z]{16}|\bxox[baprs]-[A-Za-z0-9-]{16,}")),
    ("url-credential", re.compile(rb"://[^/\s:@]+:[^/\s@]{4,}@")),
)


def findings(data):
    return [name for name, pattern in RULES if pattern.search(data)]


def selftest():
    positives = [b"/home/" + b"privateuser/source", b"private." + b"ts.net",
                 b".d" + b"sh/raw.json", b"-----BEGIN " + b"PRIVATE KEY-----",
                 b"ghp_" + b"x" * 35, b"AKIA" + b"X" * 16,
                 b"https://alice:" + b"password@example.com"]
    assert all(findings(data) for data in positives)
    assert not findings(b"https://tts.example.com http://127.0.0.1:8765 /home/user/source")


def main():
    selftest()
    files = [path for path in ROOT.rglob("*") if ".git" not in path.parts and path.is_file()
             and "__pycache__" not in path.parts and path.suffix != ".pyc"]
    violations = []
    total = 0
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or any(part in (".dsh", "_deployment", "node_modules") for part in path.relative_to(ROOT).parts):
            violations.append((rel, "private-path-or-symlink"))
        data = path.read_bytes()
        total += len(data)
        violations.extend((rel, finding) for finding in findings(data))
    blobs = blob_bytes = 0
    if (ROOT / ".git").exists():
        output = subprocess.check_output(["git", "-C", str(ROOT), "rev-list", "--objects", "--all"], text=True)
        objects = {line.split()[0] for line in output.splitlines()}
        for oid in objects:
            kind = subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "-t", oid], text=True).strip()
            if kind != "blob":
                continue
            data = subprocess.check_output(["git", "-C", str(ROOT), "cat-file", "blob", oid])
            blobs += 1
            blob_bytes += len(data)
            violations.extend((oid[:12], finding) for finding in findings(data))
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["id"] == "io.github.pavellizunov.teratts"
    assert manifest["kinds"] == ["bar-widget"] and manifest["entryPoints"] == {"barWidget": "BarWidget.qml"}
    for name in ["README.md", "LICENSE", "ATTRIBUTION.md", "docs/SERVER.md", "docs/USAGE.md", "preview.png"]:
        assert (ROOT / name).is_file(), name
    readme = (ROOT / "README.md").read_text()
    assert "omarchy plugin add" in readme and "omarchy plugin remove" in readme
    assert "own" in readme and "unsandboxed" in readme
    for required in manifest["entryPoints"].values():
        assert (ROOT / required).is_file()
    for path in ROOT.rglob("*"):
        if ".git" not in path.parts and path.is_symlink():
            violations.append((str(path.relative_to(ROOT)), "symlink"))
    for where, kind in violations:
        print(f"FAIL {where}: {kind}; value withheld")
    print(f"Public scan: {len(files)} files / {total} bytes; {blobs} reachable blobs / {blob_bytes} bytes; {len(violations)} findings")
    print("Detector positive/negative controls passed; no universal privacy/security or runtime certification.")
    return bool(violations)


if __name__ == "__main__":
    sys.exit(main())
