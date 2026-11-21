#!/usr/bin/env python3
"""Fail-closed source-tree readiness checks for Foundry Hosted Agent packaging.

This checks local prerequisites only; it does not claim azd packaging or Azure startup succeeded.
"""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
required = [
    "azure.yaml",
    "main.py",
    "requirements.txt",
    "agent/hosted_adapter.py",
    "agent/agent.py",
    "governance/policies/acs/manifest.yaml",
    "governance/policies/acs/policy/policy.rego",
    "tools/opa",
]
for relative in required:
    path = root / relative
    assert path.is_file(), f"Missing hosted deployment input: {relative}"
    print(f"PASS: required source input {relative}")

opa = root / "tools/opa"
assert os.access(opa, os.X_OK), "OPA is not executable"
result = subprocess.run([str(opa), "version"], capture_output=True, text=True, timeout=15)
assert result.returncode == 0 and "1.22.4" in result.stdout, (
    f"OPA version mismatch: {result.stdout} {result.stderr}"
)
print("PASS: pinned OPA binary executable")

ignore = (root / ".agentignore").read_text(encoding="utf-8")
for line in ignore.splitlines():
    entry = line.strip()
    if not entry or entry.startswith("#") or entry.startswith("!"):
        continue
    assert entry not in ("tools", "tools/", "tools/opa", "/tools/opa", "*.opa"), (
        f"OPA binary excluded by .agentignore: {entry}"
    )
print("PASS: no explicit OPA exclusion in root .agentignore")

main = (root / "main.py").read_text(encoding="utf-8")
for fragment in ('OPA_SOURCE = OPA_DIRECTORY / "opa"', 'OPA_RUNTIME = Path("/tmp/opa")',
                 'os.environ["ACS_OPA_PATH"]', "OPA_RUNTIME.chmod(0o755)"):
    assert fragment in main, f"Missing startup OPA wiring: {fragment}"
print("PASS: hosted startup OPA bootstrap wiring present")
print("SOURCE_PREFLIGHT_PASS: azd packaging and hosted execution still require verification")
