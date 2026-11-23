#!/usr/bin/env bash
# Prepare the OPA binary required by main.py for Foundry Hosted Agent code deployment.
# Run from the repository root before azd deploy; no sudo required.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPA_VERSION="1.22.4"
OPA_TARGET="$ROOT/tools/opa"
mkdir -p "$ROOT/tools"

if [[ ! -f "$OPA_TARGET" ]] || ! "$OPA_TARGET" version 2>/dev/null | grep -q "Version: $OPA_VERSION"; then
  case "$(uname -m)" in
    x86_64) ARCH="amd64" ;;
    *) echo "Unsupported OPA build architecture: $(uname -m)" >&2; exit 1 ;;
  esac
  TEMP_FILE="$(mktemp "$ROOT/tools/.opa.XXXXXXXX")"
  trap 'rm -f "$TEMP_FILE"' EXIT
  curl -fL --retry 3 "https://openpolicyagent.org/downloads/v${OPA_VERSION}/opa_linux_${ARCH}_static" -o "$TEMP_FILE"
  chmod 755 "$TEMP_FILE"
  "$TEMP_FILE" version | grep -q "Version: $OPA_VERSION"
  mv -f "$TEMP_FILE" "$OPA_TARGET"
  trap - EXIT
fi

chmod 755 "$OPA_TARGET"
"$OPA_TARGET" version
echo "OPA_READY=$OPA_TARGET"
echo "OPA is bundled in the agent source tree; main.py copies it to /tmp/opa at startup."
