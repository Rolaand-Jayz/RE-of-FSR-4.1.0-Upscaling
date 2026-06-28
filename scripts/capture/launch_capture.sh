#!/bin/bash
# FSR 4 Runtime Capture — Launch FF7 Rebirth with RenderDoc
# Run this on CachyOS to capture frames with FSR 4 dispatch data
#
# USAGE:  bash launch_capture.sh
#         Then press F12/PrintScreen in-game to capture a frame
#         Captures save to /tmp/fsr-capture/

set -e

CAPTURE_DIR="/tmp/fsr-capture"
GAME_DIR="/home/rolaandjayz/.steam/steam/steamapps/common/FINAL FANTASY VII REBIRTH"
GAME_EXE="End/Binaries/Win64/ff7rebirth.exe"

# Check RenderDoc
RENDERDOC_SO="/usr/lib/librenderdoc.so"
if [ ! -f "$RENDERDOC_SO" ]; then
    echo "ERROR: RenderDoc not found at $RENDERDOC_SO"
    echo "Install with: sudo pacman -S renderdoc"
    exit 1
fi

mkdir -p "$CAPTURE_DIR"

echo "================================================"
echo " FSR 4 Runtime Capture Setup"
echo "================================================"
echo ""
echo "  Capture dir:  $CAPTURE_DIR"
echo "  Game:         FF7 Rebirth (Proton)"
echo "  Renderer:     VKD3D (D3D12 → Vulkan)"
echo ""
echo "  RenderDoc:    $RENDERDOC_SO"
echo "  Capture key:  F12 or PrintScreen"
echo ""
echo "  After capturing, analyze with:"
echo "    python3 ${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}/scripts/capture.py <file>.rdc"
echo ""
echo "================================================"
echo ""

# Environment for RenderDoc + VKD3D capture
export ENABLE_VULKAN=1
export RENDERDOC_CAPTUREFILE="$CAPTURE_DIR/fsr4_frame"
export RENDERDOC_CAPOPTS=""

# VKD3D debug output (useful for confirming shader names)
export VKD3D_DEBUG=trace
export VKD3D_SHADER_DUMP_PATH="$CAPTURE_DIR/vkd3d-shaders"

# Preload RenderDoc
export LD_PRELOAD="$RENDERDOC_SO"

# Proton should pick this up via Steam's launch options
# For manual launch:
# STEAM_COMPAT_DATA_PATH=... LD_PRELOAD=... proton run "$GAME_DIR/$GAME_EXE"

echo "Ready. Launching game..."
echo "Press F12 in-game to capture a frame."
echo "Captures will appear in $CAPTURE_DIR/*.rdc"
echo ""
echo "NOTE: If launching through Steam, set these launch options instead:"
echo "  ENABLE_VULKAN=1 RENDERDOC_CAPTUREFILE=$CAPTURE_DIR/fsr4_frame LD_PRELOAD=$RENDERDOC_SO %command%"
