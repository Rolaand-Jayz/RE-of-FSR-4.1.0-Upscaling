#!/bin/bash
# FSR 4.1.0 Capture Diagnostic — tests all capture methods
set -e

echo "================================================"
echo " FSR 4.1.0 Capture Diagnostic"
echo "================================================"

RD_SO="/usr/lib/librenderdoc.so"
CAPTURE_SO="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}/tools/fsr4_capture.so"
PROXY_DLL="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}/tools/ffx_proxy.dll"
FF7R_DLL="/home/rolaandjayz/.local/share/Steam/steamapps/common/FINAL FANTASY VII REBIRTH/End/Binaries/Win64/amd_fidelityfx_upscaler_dx12.dll"
FF7R_DIR="/home/rolaandjayz/.local/share/Steam/steamapps/common/FINAL FANTASY VII REBIRTH"

PASS=0
FAIL=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "ok" ]; then
        echo "  ✅ $name"
        PASS=$((PASS+1))
    else
        echo "  ❌ $name — $result"
        FAIL=$((FAIL+1))
    fi
}

echo ""
echo "[1] RenderDoc library"
if [ -f "$RD_SO" ]; then
    check "librenderdoc.so exists" "ok"
    echo "     Size: $(stat -c%s $RD_SO) bytes"
else
    check "librenderdoc.so" "NOT FOUND"
fi

echo ""
echo "[2] RenderDoc Vulkan layer"
if [ -f /etc/vulkan/implicit_layer.d/renderdoc_capture.json ]; then
    check "Vulkan implicit layer registered" "ok"
    ENABLE_VAR=$(grep -o 'ENABLE_VULKAN_[A-Z_]*' /etc/vulkan/implicit_layer.d/renderdoc_capture.json | head -1)
    check "Required env var: $ENABLE_VAR=1" "ok"
else
    check "Vulkan layer" "NOT REGISTERED"
fi

echo ""
echo "[3] Vulkan LD_PRELOAD hook"
if [ -f "$CAPTURE_SO" ]; then
    check "fsr4_capture.so exists" "ok"
else
    check "fsr4_capture.so" "NOT FOUND"
fi

echo ""
echo "[4] FFX Proxy DLL"
if [ -f "$PROXY_DLL" ]; then
    check "ffx_proxy.dll exists" "ok"
else
    check "ffx_proxy.dll" "NOT FOUND"
fi

echo ""
echo "[5] FF7R target game"
if [ -f "$FF7R_DLL" ]; then
    check "amd_fidelityfx_upscaler_dx12.dll found" "ok"
    FSIZE=$(stat -c%s "$FF7R_DLL")
    echo "     Size: $FSIZE bytes"
    if strings "$FF7R_DLL" | grep -q "abd3160"; then
        check "FSR 4.1.0 build abd3160 confirmed" "ok"
    else
        check "FSR version" "abd3160 build string not found"
    fi
else
    check "FF7R upscaler DLL" "NOT FOUND"
fi

echo ""
echo "[6] OptiScaler"
OPTISCALER="$FF7R_DIR/End/Binaries/Win64/dlssg_to_fsr3_amd_is_better.dll"
if [ -f "$OPTISCALER" ]; then
    check "OptiScaler DLL present" "ok"
else
    check "OptiScaler" "NOT FOUND — FSR 4 won't activate without it"
fi

echo ""
echo "[7] Proxy DLL installation status"
REAL_DLL="$FF7R_DIR/End/Binaries/Win64/dll_v410_real.dll"
if [ -f "$REAL_DLL" ]; then
    check "Proxy currently INSTALLED" "ok"
    echo "     ⚠️  Run remove-proxy to restore original"
else
    check "Original DLL in place (no proxy active)" "ok"
fi

echo ""
echo "================================================"
echo " Results: $PASS passed, $FAIL failed"
echo ""
echo " CORRECTED CAPTURE INSTRUCTIONS:"
echo ""
echo " Method 1 — RenderDoc (recommended):"
echo "   Steam launch options for FF7R:"
echo "   ENABLE_VULKAN_RENDERDOC_CAPTURE=1 \\"
echo "   RENDERDOC_CAPTUREFILE=${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}/runtime-capture/fsr4_ff7r \\"
echo "   VKD3D_DEBUG=trace \\"
echo "   VKD3D_SHADER_DUMP_PATH=${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}/runtime-capture/vkd3d-shaders \\"
echo "   %command%"
echo ""
echo " Method 2 — Vulkan LD_PRELOAD (dispatch logging):"
echo "   Steam launch options:"
echo "   LD_PRELOAD=${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}/tools/fsr4_capture.so \\"
echo "   %command%"
echo ""
echo " Method 3 — FFX Proxy DLL (API-level):"
echo "   bash ${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}/tools/setup_capture.sh install-proxy"
echo "   Then launch FF7R normally through Steam"
echo "================================================"
