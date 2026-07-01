#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ORIGINAL_DLL="${ORIGINAL_DLL:-${1:-}}"

cd "$SCRIPT_DIR"

if [[ -z "$ORIGINAL_DLL" || ! -f "$ORIGINAL_DLL" ]]; then
  echo "ERROR: provide the original fsr_data.dll via ORIGINAL_DLL=/path/to/fsr_data.dll or as argv[1]" >&2
  exit 2
fi

echo "========================================"
echo " FSR 4.1.0 fsr_data.dll — independent rebuild check"
echo "========================================"
echo ""

echo "STEP 1: Compile reconstructed C source"
echo "  Source:    fsr_data.c"
echo "  Exports:   fsr_data.def"
echo "  Weights:   $REPO_ROOT/extracted/v410_initializers/"
echo "  Compiler:  ${CC:-x86_64-w64-mingw32-gcc}"
echo ""
bash build.sh 2>&1 | grep -v "^$"
echo ""

echo "STEP 2: Compare rebuilt DLL against original WITHOUT copying original bytes"
echo ""
python3 compare_sections.py \
  --original "$ORIGINAL_DLL" \
  --rebuilt "$SCRIPT_DIR/fsr_data_prepatch.dll" \
  --json-out "$SCRIPT_DIR/section-comparison.json"
echo ""

echo "========================================"
echo " Comparison complete."
echo "========================================"
echo "This is not a bit-identical proof unless every region reports MATCH without patching."
