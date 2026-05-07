#!/usr/bin/env bash
# ================================================================
#   Wake Orion on this Mac
#   Double-click this file. No code-signing -- this is open source.
#   .command files bypass Gatekeeper, AND USB-borne files on
#   FAT32/exFAT carry no com.apple.quarantine attribute. Result:
#   ZERO security warnings on macOS Sonoma / Sequoia.
#
#   What this does:
#   - If the drive already has an Orion brain (you've used Orion
#     before), this just wires THIS Mac to wake him here. ~30 seconds.
#   - If the drive has no brain (first-ever Orion), runs the
#     conversational setup so he can introduce himself.
# ================================================================

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo ""
echo "================================================================"
echo "   Waking Orion on this Mac..."
echo "   Source: $SCRIPT_DIR"
echo "================================================================"
echo ""

# ExFAT/FAT32 don't preserve the +x bit, so we invoke install.sh via
# bash directly rather than relying on its executable bit.
bash "$SCRIPT_DIR/install.sh"
EXITCODE=$?

echo ""
if [ "$EXITCODE" = "0" ]; then
    echo "[OK] Orion is awake here."
else
    echo "[WARN] Wake exited with code $EXITCODE."
fi
echo ""
echo "Press Enter to close this window."
read -r _

exit $EXITCODE
