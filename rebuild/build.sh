#!/bin/bash
# Build fsr_data.dll from reconstructed source + extracted weight blobs
# Produces fsr_data_prepatch.dll for independent section comparison
# Requires: x86_64-w64-mingw32-gcc (MinGW cross-compiler)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Building fsr_data.dll ==="
echo "Source:     fsr_data.c"
echo "Exports:    fsr_data.def"
echo "Weights:    ../extracted/v410_initializers/"
echo ""

CC="${CC:-x86_64-w64-mingw32-gcc}"

"$CC" -shared -O2 \
    -Wl,--image-base=0x370b10000 \
    -o fsr_data_prepatch.dll \
    fsr_data.c fsr_data.def

echo ""
echo "=== Build complete ==="
echo "Pre-patch DLL:"
md5sum fsr_data_prepatch.dll
ls -la fsr_data_prepatch.dll
echo ""
echo "Expected pre-patch MD5: cddca9acec4e79776cb180d2ee337dc6"
echo ""
echo "To compare against the original without copying original bytes, run:"
echo "  ORIGINAL_DLL=/path/to/original/fsr_data.dll python3 pe_patcher.py --rebuilt fsr_data_prepatch.dll"
echo ""
echo "Historical patched-final MD5 (not independent proof): cb1aa61c71c33b25549ed59c1551d661"
