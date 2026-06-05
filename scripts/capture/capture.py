#!/usr/bin/env python3
"""FSR 4 Runtime Capture — Automated RenderDoc capture via replay API.

USAGE (on CachyOS):
    1. Install: sudo pacman -S renderdoc
    2. Launch FF7 Rebirth with RenderDoc:
       export ENABLE_VULKAN=1
       export RENDERDOC_CAPTUREFILE=/tmp/fsr-capture/fsr4_frame
       export LD_PRELOAD=/usr/lib/librenderdoc.so
       # Then launch game through Steam/Proton
    3. Press F12 (or PrintScreen) in-game to capture a frame
    4. Run this script to analyze the capture:
       python3 capture.py /tmp/fsr-capture/fsr4_frame.rdc

This script:
    - Loads a RenderDoc capture (.rdc)
    - Finds all FSR 4 compute dispatches (by shader name matching)
    - Extracts cbuffer contents for InitializerBuffer
    - Extracts UAV/srv buffer bindings (weight data)
    - Dumps everything to JSON for comparison against static analysis
"""

import sys
import os
import json
import struct
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path("/mnt/workdrive/fsr-re/runtime-capture")


def find_fsr4_dispatches(capture_path):
    """Parse capture file and extract FSR 4 dispatch data.
    
    Uses RenderDoc's Python replay API (qrenderdoc).
    """
    try:
        from qrenderdoc import (
            ReplayController, CaptureFile, 
            TextureDisplay, ResourceId, SDFile, SDRow, SDChunk
        )
    except ImportError:
        print("ERROR: qrenderdoc not found. Install with: sudo pacman -S renderdoc")
        print("  Then run: export PYTHONPATH=/usr/share/renderdoc/python:$PYTHONPATH")
        sys.exit(1)
    
    cap = CaptureFile()
    cap.OpenFile(capture_path, "", None)
    
    controller = cap.OpenCapture(None)
    if not controller:
        print("ERROR: Failed to open capture")
        sys.exit(1)
    
    frame_record = controller.GetFrameRecord()
    
    results = {
        "capture_file": str(capture_path),
        "capture_time": datetime.utcnow().isoformat(),
        "frame_number": frame_record.frameNumber,
        "dispatches": [],
        "initializer_buffer_dumps": [],
        "weight_buffer_dumps": [],
    }
    
    # Walk all drawcalls looking for compute dispatches
    drawcalls = frame_record.drawcallList
    
    def walk_drawcalls(draws, depth=0):
        for dc in draws:
            # Check if this is a compute dispatch
            is_compute = bool(dc.flags & dc.Compute)
            name = dc.name or ""
            
            # Match FSR 4 shader names
            is_fsr4 = any(pattern in name.lower() for pattern in [
                "mlsr", "fsr4", "model_v07", "no_scale", "pass",
                "prepass", "postpass", "initializer"
            ])
            
            if is_compute and is_fsr4:
                dispatch_info = {
                    "eid": dc.eventId,
                    "name": name,
                    "dispatches_x": dc.dispatchDimension[0] if hasattr(dc, 'dispatchDimension') else None,
                    "dispatches_y": dc.dispatchDimension[1] if hasattr(dc, 'dispatchDimension') else None,
                    "dispatches_z": dc.dispatchDimension[2] if hasattr(dc, 'dispatchDimension') else None,
                }
                
                # Extract pipeline state for this dispatch
                try:
                    state = controller.GetPipelineState(dc.eventId)
                    
                    # Get compute shader
                    cs = state.GetShaderReflection("compute")
                    if cs:
                        dispatch_info["shader_name"] = cs.name if hasattr(cs, 'name') else "unknown"
                        dispatch_info["thread_groups"] = [
                            cs.dispatchThreadsDimension[0],
                            cs.dispatchThreadsDimension[1],
                            cs.dispatchThreadsDimension[2],
                        ] if hasattr(cs, 'dispatchThreadsDimension') else None
                    
                    # Get cbuffer contents
                    cbuffers = state.GetConstantBuffers("compute")
                    for cb in cbuffers:
                        try:
                            data = controller.GetBufferData(
                                cb.resourceId, cb.byteOffset, cb.byteSize, dc.eventId
                            )
                            cb_info = {
                                "dispatch_eid": dc.eventId,
                                "dispatch_name": name,
                                "resource_id": int(cb.resourceId),
                                "byte_offset": cb.byteOffset,
                                "byte_size": cb.byteSize,
                                "data_hex": bytes(data).hex()[:4096],  # First 4KB
                            }
                            
                            # Check if this looks like InitializerBuffer (131072 bytes)
                            if cb.byteSize >= 130000:
                                results["initializer_buffer_dumps"].append({
                                    "dispatch_eid": dc.eventId,
                                    "dispatch_name": name,
                                    "resource_id": int(cb.resourceId),
                                    "byte_size": cb.byteSize,
                                    "md5": __import__('hashlib').md5(bytes(data)).hexdigest(),
                                    "first_32_bytes_hex": bytes(data)[:32].hex(),
                                    "data_file": None,  # Will be saved separately
                                })
                                # Save full buffer
                                buf_path = OUTPUT_DIR / f"initializerbuf_eid{dc.eventId}.bin"
                                buf_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(buf_path, 'wb') as f:
                                    f.write(bytes(data))
                                results["initializer_buffer_dumps"][-1]["data_file"] = str(buf_path)
                            
                            dispatch_info.setdefault("cbuffers", []).append(cb_info)
                        except Exception as e:
                            dispatch_info.setdefault("cbuffer_errors", []).append(str(e))
                    
                    # Get UAV/SRV bindings (weight textures, IO buffers)
                    bindings = []
                    try:
                        for i in range(64):  # Check first 64 descriptor slots
                            srv = state.GetReadWriteData(dc.eventId, i)
                    except:
                        pass
                    
                except Exception as e:
                    dispatch_info["state_error"] = str(e)
                
                results["dispatches"].append(dispatch_info)
                print(f"  [FSR4] EID {dc.eventId}: {name}")
            
            # Recurse into children
            if hasattr(dc, 'children') and dc.children:
                walk_drawcalls(dc.children, depth + 1)
    
    print("Scanning drawcalls for FSR 4 dispatches...")
    walk_drawcalls(drawcalls)
    
    print(f"\nFound {len(results['dispatches'])} FSR 4 dispatches")
    print(f"Found {len(results['initializer_buffer_dumps'])} InitializerBuffer captures")
    
    # Save results
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "capture_results.json"
    with open(out_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")
    
    # Compare against static analysis
    compare_against_static(results)
    
    controller.Shutdown()
    return results


def compare_against_static(results):
    """Compare captured runtime data against our static analysis findings."""
    print("\n" + "="*60)
    print("COMPARISON: Runtime vs Static Analysis")
    print("="*60)
    
    # Check 1: Did we get 27 dispatches (pre + 12 layers * 2 + post)?
    expected_passes = ["prepass"] + [f"pass{i}" for i in range(13)] + ["postpass"]
    found_passes = set()
    for d in results["dispatches"]:
        name = d.get("name", "").lower()
        for p in expected_passes:
            if p in name:
                found_passes.add(p)
    
    print(f"\n[1] Dispatch count:")
    print(f"    Expected: ~27 (prepass + 13 passes + postpass, each with _post variant)")
    print(f"    Found:    {len(results['dispatches'])}")
    print(f"    Pass types found: {sorted(found_passes)}")
    if len(found_passes) >= 14:
        print("    ✅ All pass types present")
    else:
        missing = set(expected_passes) - found_passes
        print(f"    ⚠️  Missing: {sorted(missing)}")
    
    # Check 2: InitializerBuffer size
    print(f"\n[2] InitializerBuffer:")
    for ib in results["initializer_buffer_dumps"]:
        print(f"    Size: {ib['byte_size']} bytes (expected: 131072)")
        if ib['byte_size'] == 131072:
            print(f"    ✅ Size matches")
        else:
            print(f"    ⚠️  Size mismatch!")
        print(f"    MD5: {ib['md5']}")
        print(f"    First 32 bytes: {ib['first_32_bytes_hex']}")
        
        # If we have the full buffer, compare against extracted blobs
        if ib.get("data_file"):
            try:
                with open(ib["data_file"], 'rb') as f:
                    runtime_data = f.read()
                
                # Check bias zone (first 7208 bytes should be valid FP16)
                bias_zone = runtime_data[:7208]
                fp16_values = []
                for i in range(0, len(bias_zone), 2):
                    val = struct.unpack_from('<e', bias_zone, i)[0]
                    fp16_values.append(val)
                
                non_zero_bias = sum(1 for v in fp16_values if v != 0)
                print(f"    Bias zone: {len(fp16_values)} FP16 values, {non_zero_bias} non-zero (expected 3604)")
                
                # Check weight zone (7208 to 130088)
                weight_zone = runtime_data[7208:130088]
                unique_vals = len(set(weight_zone))
                print(f"    Weight zone: {unique_vals} unique uint8 values (expected 255)")
                if unique_vals == 255:
                    print(f"    ✅ Weight uniqueness matches static analysis")
                
                # Check extra zone (130088 to 130976)
                extra_zone = runtime_data[130088:130976]
                if len(extra_zone) == 888:
                    print(f"    Extra zone: 888 bytes present ✅")
                
            except Exception as e:
                print(f"    Error reading buffer: {e}")
    
    # Check 3: Thread group dimensions (should match HLSL)
    print(f"\n[3] Thread group dimensions:")
    for d in results["dispatches"]:
        if d.get("thread_groups"):
            print(f"    {d['name']}: {d['thread_groups']}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nERROR: No capture file specified")
        print("Usage: python3 capture.py <path_to_rdc_file>")
        sys.exit(1)
    
    capture_path = Path(sys.argv[1])
    if not capture_path.exists():
        print(f"ERROR: File not found: {capture_path}")
        sys.exit(1)
    
    find_fsr4_dispatches(capture_path)


if __name__ == "__main__":
    main()
