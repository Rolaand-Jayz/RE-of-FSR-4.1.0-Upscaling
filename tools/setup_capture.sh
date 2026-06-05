#!/bin/bash
# FSR 4.1.0 Runtime Capture Setup
# Prepares everything for capturing FSR dispatch data on CachyOS
#
# USAGE:
#   source setup_capture.sh          # Set up environment
#   bash setup_capture.sh ff7r       # Launch FF7R with RenderDoc
#   bash setup_capture.sh split      # Launch Split Fiction with RenderDoc
#   bash setup_capture.sh analyze    # Analyze captured .rdc file
#
set -e

BASE="/mnt/workdrive/fsr-re"
CAPTURE_DIR="$BASE/runtime-capture"
TOOLS="$BASE/tools"

# Game paths
FF7R_DIR="/home/rolaandjayz/.local/share/Steam/steamapps/common/FINAL FANTASY VII REBIRTH"
FF7R_EXE="End/Binaries/Win64/ff7rebirth.exe"
FF7R_UPSCALER_DLL="$FF7R_DIR/End/Binaries/Win64/amd_fidelityfx_upscaler_dx12.dll"

SPLIT_DIR="/home/rolaandjayz/.local/share/Steam/steamapps/common/Split Fiction"
SPLIT_EXE="Split/Binaries/Win64/SplitFiction.exe"

RENDERDOC_SO="/usr/lib/librenderdoc.so"
PROTON_DIR="/home/rolaandjayz/.local/share/Steam/steamapps/common/Proton 11.0"

mkdir -p "$CAPTURE_DIR"

setup_proxy() {
    echo "[SETUP] Installing FFX proxy DLL for FF7R..."
    
    if [ ! -f "$FF7R_UPSCALER_DLL" ]; then
        echo "ERROR: FF7R upscaler DLL not found at $FF7R_UPSCALER_DLL"
        exit 1
    fi
    
    # Check if proxy is already installed
    if [ -f "$FF7R_DIR/End/Binaries/Win64/dll_v410_real.dll" ]; then
        echo "  Proxy already installed (dll_v410_real.dll exists)"
        return
    fi
    
    # Backup original
    echo "  Backing up original amd_fidelityfx_upscaler_dx12.dll..."
    cp "$FF7R_UPSCALER_DLL" "$FF7R_DIR/End/Binaries/Win64/dll_v410_real.dll"
    
    # Install proxy
    echo "  Installing proxy DLL..."
    cp "$TOOLS/ffx_proxy.dll" "$FF7R_UPSCALER_DLL"
    
    echo "  Proxy installed. Original backed up as dll_v410_real.dll"
}

remove_proxy() {
    echo "[RESTORE] Removing FFX proxy from FF7R..."
    if [ -f "$FF7R_DIR/End/Binaries/Win64/dll_v410_real.dll" ]; then
        cp "$FF7R_DIR/End/Binaries/Win64/dll_v410_real.dll" "$FF7R_UPSCALER_DLL"
        rm "$FF7R_DIR/End/Binaries/Win64/dll_v410_real.dll"
        echo "  Original DLL restored."
    else
        echo "  No proxy found — nothing to restore."
    fi
}

launch_ff7r_renderdoc() {
    echo "================================================"
    echo " FSR 4.1.0 Capture — FF7 Rebirth + RenderDoc"
    echo "================================================"
    echo ""
    echo "  DLL: amd_fidelityfx_upscaler_dx12.dll (FSR 4.1.0, abd3160)"
    echo "  OptiScaler: Fsr4Update=true"
    echo "  Renderer: VKD3D-Proton (D3D12 -> Vulkan)"
    echo "  Capture key: F12 or PrintScreen"
    echo "  Output: $CAPTURE_DIR/"
    echo ""
    echo "  IMPORTANT: Run these commands as rolaandjayz!"
    echo "  (The Steam session and Proton need the main user)"
    echo ""
    echo "  Steam launch options for FF7R:"
    echo ""
    echo "  ENABLE_VULKAN=1 \\"
    echo "  RENDERDOC_CAPTUREFILE=$CAPTURE_DIR/fsr4_ff7r_frame \\"
    echo "  VKD3D_DEBUG=trace \\"
    echo "  VKD3D_SHADER_DUMP_PATH=$CAPTURE_DIR/vkd3d-shaders \\"
    echo "  LD_PRELOAD=$RENDERDOC_SO \\"
    echo "  %command%"
    echo ""
    echo "  Or launch manually from Steam with those env vars."
    echo ""
    echo "  After capture, analyze with:"
    echo "    PYTHONPATH=/usr/share/renderdoc/python:\$PYTHONPATH \\"
    echo "    python3 $BASE/scripts/capture/capture.py $CAPTURE_DIR/fsr4_ff7r_frame.rdc"
    echo "================================================"
}

launch_ff7r_proxy() {
    echo "================================================"
    echo " FSR 4.1.0 Capture — FF7 Rebirth + FFX Proxy"
    echo "================================================"
    echo ""
    echo "  The proxy DLL intercepts ffxDispatch/ffxCreateContext"
    echo "  and logs descriptor bytes to ffx_capture.log in the game dir."
    echo ""
    echo "  Steps:"
    echo "  1. bash $TOOLS/setup_capture.sh install-proxy"
    echo "  2. Launch FF7R through Steam (normal launch, no extra env)"
    echo "  3. Play until FSR is active (enter a 3D scene)"
    echo "  4. Exit game"
    echo "  5. Check: $FF7R_DIR/End/Binaries/Win64/ffx_capture.log"
    echo "  6. Restore: bash $TOOLS/setup_capture.sh remove-proxy"
    echo ""
    echo "  The proxy logs hex dumps of CreateContext and Dispatch"
    echo "  descriptors, which contain cbuffer layout and binding info."
    echo "================================================"
}

launch_split_renderdoc() {
    echo "================================================"
    echo " FSR Capture — Split Fiction + RenderDoc"
    echo "================================================"
    echo ""
    echo "  NOTE: Split Fiction uses amd_fidelityfx_dx12.dll (combined)"
    echo "  This DLL has FSR 2/3 + Frame Gen, NOT the separate upscaler."
    echo "  It will NOT capture FSR 4.1 upscaler passes."
    echo ""
    echo "  Useful for: Frame generation dispatch patterns, general FSR capture"
    echo "  NOT useful for: FSR 4.1 upscaler tensor offset mapping"
    echo ""
    echo "  Steam launch options for Split Fiction:"
    echo ""
    echo "  ENABLE_VULKAN=1 \\"
    echo "  RENDERDOC_CAPTUREFILE=$CAPTURE_DIR/fsr_split_frame \\"
    echo "  VKD3D_DEBUG=trace \\"
    echo "  LD_PRELOAD=$RENDERDOC_SO \\"
    echo "  %command%"
    echo "================================================"
}

launch_ldpreload() {
    echo "================================================"
    echo " FSR 4.1.0 Capture — Vulkan LD_PRELOAD Hook"
    echo "================================================"
    echo ""
    echo "  The fsr4_capture.so hooks vkCmdDispatch to log all"
    echo "  compute dispatches with thread group counts and descriptor sets."
    echo ""
    echo "  Steam launch options:"
    echo ""
    echo "  LD_PRELOAD=$TOOLS/fsr4_capture.so \\"
    echo "  %command%"
    echo ""
    echo "  Output: $CAPTURE_DIR/dispatch_log.txt"
    echo ""
    echo "  Good for: Getting dispatch group dimensions for all 27 passes"
    echo "  Limitation: Cannot read cbuffer contents or buffer data"
    echo "================================================"
}

verify_setup() {
    echo "================================================"
    echo " Capture Environment Verification"
    echo "================================================"
    
    echo ""
    echo "[1] RenderDoc:"
    if [ -f "$RENDERDOC_SO" ]; then
        echo "    OK: $RENDERDOC_SO"
    else
        echo "    MISSING: Install with 'sudo pacman -S renderdoc'"
    fi
    
    echo ""
    echo "[2] FFX Proxy DLL:"
    if [ -f "$TOOLS/ffx_proxy.dll" ]; then
        echo "    OK: $TOOLS/ffx_proxy.dll"
    else
        echo "    MISSING: Build with 'x86_64-w64-mingw32-gcc -shared -o $TOOLS/ffx_proxy.dll $TOOLS/ffx_capture_proxy.c -lkernel32 -luser32'"
    fi
    
    echo ""
    echo "[3] Vulkan capture .so:"
    if [ -f "$TOOLS/fsr4_capture.so" ]; then
        echo "    OK: $TOOLS/fsr4_capture.so"
    else
        echo "    MISSING: Build with 'gcc -shared -fPIC -O2 -o $TOOLS/fsr4_capture.so $TOOLS/fsr4_capture.c -ldl'"
    fi
    
    echo ""
    echo "[4] FF7R upscaler DLL:"
    if [ -f "$FF7R_UPSCALER_DLL" ]; then
        FSIZE=$(stat -c%s "$FF7R_UPSCALER_DLL")
        echo "    OK: $FF7R_UPSCALER_DLL ($FSIZE bytes)"
        strings "$FF7R_UPSCALER_DLL" | grep -E 'abd3160|4\.1\.0|Mar 20 2026' | head -3
    else
        echo "    NOT FOUND"
    fi
    
    echo ""
    echo "[5] Proton:"
    if [ -d "$PROTON_DIR" ]; then
        echo "    OK: $PROTON_DIR"
    else
        echo "    Checking alternatives..."
        ls /home/rolaandjayz/.local/share/Steam/steamapps/common/ | grep -i proton 2>/dev/null || echo "    No Proton found"
    fi
    
    echo ""
    echo "[6] Capture output dir:"
    mkdir -p "$CAPTURE_DIR"
    echo "    OK: $CAPTURE_DIR"
    
    echo ""
    echo "[7] MinGW cross-compiler:"
    which x86_64-w64-mingw32-gcc 2>/dev/null && echo "    OK" || echo "    MISSING"
    
    echo ""
    echo "[8] Capture analysis script:"
    if [ -f "$BASE/scripts/capture/capture.py" ]; then
        echo "    OK: $BASE/scripts/capture/capture.py"
    else
        echo "    MISSING"
    fi
    
    echo ""
    echo "[9] Analysis pipeline (post-capture):"
    if [ -f "$BASE/scripts/capture/analyze_capture.py" ]; then
        echo "    OK: analyze_capture.py"
    else
        echo "    WILL CREATE on first capture"
    fi
}

# ============ Main ============
case "${1:-help}" in
    verify)
        verify_setup
        ;;
    install-proxy)
        setup_proxy
        ;;
    remove-proxy)
        remove_proxy
        ;;
    ff7r)
        launch_ff7r_renderdoc
        ;;
    ff7r-proxy)
        launch_ff7r_proxy
        ;;
    split)
        launch_split_renderdoc
        ;;
    ldpreload)
        launch_ldpreload
        ;;
    help|*)
        echo "FSR 4.1.0 Runtime Capture Setup"
        echo ""
        echo "Commands:"
        echo "  verify          Check all capture tools are ready"
        echo "  install-proxy   Install FFX proxy DLL into FF7R"
        echo "  remove-proxy    Restore original FF7R DLL"
        echo "  ff7r            Show RenderDoc launch instructions for FF7R"
        echo "  ff7r-proxy      Show FFX proxy launch instructions for FF7R"
        echo "  split           Show RenderDoc launch instructions for Split Fiction"
        echo "  ldpreload       Show LD_PRELOAD Vulkan hook launch instructions"
        echo "  analyze         Analyze a captured .rdc file (not yet implemented)"
        echo ""
        echo "Recommended capture flow:"
        echo "  1. bash setup_capture.sh verify"
        echo "  2. bash setup_capture.sh ff7r  (copy Steam launch options)"
        echo "  3. Launch FF7R via Steam, press F12 to capture"
        echo "  4. Analyze: python3 ../scripts/capture/capture.py <file>.rdc"
        ;;
esac
