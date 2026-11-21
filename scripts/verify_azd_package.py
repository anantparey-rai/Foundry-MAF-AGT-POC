#!/usr/bin/env python3
"""Inspect azd-produced archive without extracting or publishing its contents."""
import sys
import zipfile
from pathlib import Path

if len(sys.argv) != 2:
    raise SystemExit("Usage: python scripts/verify_azd_package.py <azd-package.zip>")
archive = Path(sys.argv[1])
assert archive.is_file(), f"azd package not found: {archive}"
required = [
    "main.py", "requirements.txt", "agent/agent.py",
    "agent/hosted_adapter.py", "governance/policies/acs/manifest.yaml",
    "governance/policies/acs/policy/policy.rego", "tools/opa",
]
with zipfile.ZipFile(archive) as z:
    names = {name.removeprefix("./").replace("\\", "/") for name in z.namelist()}
    for path in required:
        assert path in names, f"AZD_PACKAGE_MISSING: {path}"
        assert z.getinfo(path).file_size > 0, f"AZD_PACKAGE_EMPTY: {path}"
        print(f"PASS: azd archive includes {path}")
    assert not any(p.startswith(".env") or "/.env" in p or p.startswith(".git/") for p in names), "Potential sensitive files in package"
    print(f"AZD_PACKAGE_VERIFIED: {len(names)} entries; {archive.stat().st_size} bytes")
