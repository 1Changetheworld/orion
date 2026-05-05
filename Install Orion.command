#!/usr/bin/env bash
# ================================================================
#   ORION installer for macOS
#   Double-click this file. No code-signing -- this is open source.
#   .command files bypass Gatekeeper, AND USB-borne files on
#   FAT32/exFAT carry no com.apple.quarantine attribute. Result:
#   ZERO security warnings on macOS Sonoma / Sequoia.
# ================================================================

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

echo ""
echo "================================================================"
echo "   ORION -- portable AI memory"
echo "   Installing on this Mac..."
echo "   Source: $SCRIPT_DIR"
echo "================================================================"
echo ""

# ExFAT/FAT32 don't preserve the +x bit, so we invoke install.sh via
# bash directly rather than relying on its executable bit.
bash "$SCRIPT_DIR/install.sh"
EXITCODE=$?

echo ""
if [ "$EXITCODE" = "0" ]; then
    echo "[OK] Install completed."
else
    echo "[WARN] Install exited with code $EXITCODE."
fi
echo ""
echo "Press Enter to close this window."
read -r _

exit $EXITCODE
