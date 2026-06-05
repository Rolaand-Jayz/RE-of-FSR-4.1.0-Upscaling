#!/bin/bash
# FSR 4.1.0 Runtime Capture — CORRECTED RenderDoc launch
#
# CRITICAL FIX: The original launch script used ENABLE_VULKAN=1 — WRONG.
# RenderDoc's Vulkan implicit layer requires ENABLE_VULKAN_RENDERDOC_CAPTURE=1.
# Without this, RenderDoc never hooks into the Vulkan instance created by VKD3D-Proton.
#
set -e

CAPTURE_DIR="/mnt/workdrive/fsr-re/runtime-capture"
RENDERDOC_SO="/usr/lib/librenderdoc.so"

mkdir -p "$CAPTURE_DIR"

echo "================================================"
echo " FSR 4.1.0 Capture — FF7 Rebirth + RenderDoc"
echo "================================================"
echo ""
echo " Copy these Steam launch options for FF7R:"
echo ""
echo "  ENABLE_VULKAN_RENDERDOC_CAPTURE=1 \\"
echo "  RENDERDOC_CAPTUREFILE=$CAPTURE_DIR/fsr4_ff7r \\"
echo "  RENDERDOC_CAPOPTS=\"\" \\"
echo "  VKD3D_DEBUG=trace \\"
echo "  VKD3D_SHADER_DUMP_PATH=$CAPTURE_DIR/vkd3d-shaders \\"
echo "  %command%"
echo ""
echo "  Press F12 or PrintScreen in-game to capture."
echo "  Captures save to $CAPTURE_DIR/*.rdc"
echo ""
echo "=== After capture, analyze: ==="
echo "  PYTHONPATH=/usr/share/renderdoc/python:\$PYTHONPATH \\"
echo "  python3 /mnt/workdrive/fsr-re/scripts/capture/capture.py $CAPTURE_DIR/fsr4_ff7r.rdc"
echo ""
echo "================================================"
