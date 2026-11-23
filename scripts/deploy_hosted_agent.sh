#!/usr/bin/env bash
# The supported deployment entry point: bundle OPA before invoking azd.
# Run from any working directory; requires an existing azd environment.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f azure.yaml ]]; then echo "Missing azure.yaml" >&2; exit 1; fi
bash scripts/prepare_opa.sh
test -x tools/opa || { echo "OPA_PREDEPLOY_FAILED: tools/opa missing" >&2; exit 1; }
tools/opa version
echo "OPA_PREDEPLOY_VERIFIED: bundled binary exists"
# Do not run azd provision; this targets the existing Foundry project.
azd deploy foundry-maf-agt-poc "$@"
