#!/usr/bin/env python3
"""
FSR 4.1.0 Dispatch Extractor — RenderDoc Python Script
Run inside RenderDoc's Python Shell (Tools → Python Shell)

This script opens a .rdc capture, finds all compute dispatch calls,
extracts cbuffer contents, resource bindings, dispatch dimensions,
and identifies which dispatches belong to the FSR 4 upscaler pipeline.

Output: fsr4_dispatches.json (~1-5 MB)
"""

import json
import os
import struct
import sys
from datetime import datetime

# Try importing renderdoc module
try:
    import renderdoc
    import qrenderdoc
except ImportError:
    print("ERROR: This script must be run inside RenderDoc's Python Shell.")
    print("  1. Open RenderDoc")
    print("  2. Open your capture (.rdc file)")
    print("  3. Go to Tools → Python Shell")
    print("  4. Paste this script and press Enter")
    sys.exit(1)

OUTPUT_FILE = os.path.join(os.path.expanduser("~"), "Desktop", "fsr4_dispatches.json")

def identify_fsr_pass(shader_name):
    """Check if a shader belongs to the FSR 4 upscaler pipeline."""
    if not shader_name:
        return None, None
    
    # FSR 4.1 model shader names
    prefix = "fsr4_model_v07_fp8_no_scale_"
    if prefix in shader_name:
        pass_name = shader_name.split(prefix)[-1]
        
        # Categorize
        if pass_name == "prepass":
            return "prepass", "encoder"
        elif pass_name == "postpass":
            return "postpass", "decoder"
        elif pass_name.endswith("_post"):
            return pass_name, "scatter"
        elif pass_name.startswith("pass"):
            try:
                num = int(pass_name.replace("pass", ""))
                if 1 <= num <= 12:
                    return pass_name, "ml_body"
            except ValueError:
                pass
        return pass_name, "unknown"
    
    # FSR 3.1 / FSR 4 helper shaders
    fsr_markers = ["ffx_fsr", "FSR", "fsr3", "fsr4", "rcas", "rcas_pass",
                   "spatial", "temporal", "accumulate", "reconstruct"]
    for marker in fsr_markers:
        if marker.lower() in shader_name.lower():
            return shader_name, "auxiliary"
    
    return None, None

def extract_cbuffer_data(pipe, cbuffer_slot):
    """Extract raw bytes from a constant buffer."""
    try:
        cbuffer = pipe.GetConstantBuffer(cbuffer_slot, 0)
        if cbuffer.resourceId == renderdoc.ResourceId.Null:
            return None
        
        # Try to get the buffer data
        data = cbuffer.GetContents()
        if data:
            return data.hex()
        return None
    except Exception as e:
        return f"error: {str(e)}"

def extract_descriptor_data(controller, pipe, slot, desc_type):
    """Extract descriptor/SRV/UAV info."""
    try:
        if desc_type == "SRV":
            desc = pipe.GetShaderResource(slot, 0)
        elif desc_type == "UAV":
            desc = pipe.GetUnorderedAccessView(slot, 0)
        else:
            return None
        
        if desc.resourceId == renderdoc.ResourceId.Null:
            return None
        
        return {
            "resource_id": str(desc.resourceId),
            "format": str(desc.format) if hasattr(desc, 'format') else "unknown",
        }
    except Exception:
        return None

def analyze_capture(filename):
    """Main analysis function."""
    print(f"Opening capture: {filename}")
    
    # Open the capture
    controller = None
    try:
        state = renderdoc.OpenCaptureFile()
        result = state.OpenFile(filename, "", None)
        if result != renderdoc.ReplayStatus.Succeeded:
            print(f"Failed to open capture: {result}")
            return
        
        controller = state.OpenCapture(None)
        if not controller:
            print("Failed to get replay controller")
            return
        
        # Get frame info
        frame_record = controller.GetFrameRecord()
        print(f"Frame: {frameRecord.frameNumber}, Duration: {frameRecord.duration}")
        
        # Collect all drawcalls
        drawcalls = controller.GetDrawcalls()
        
        results = {
            "capture_file": filename,
            "timestamp": datetime.now().isoformat(),
            "frame_info": {
                "frame_number": frame_record.frameNumber,
                "duration": frame_record.duration,
                "total_drawcalls": len(drawcalls),
            },
            "fsr_dispatches": [],
            "all_compute_dispatches": [],
        }
        
        dispatch_idx = 0
        fsr_count = 0
        
        def process_drawcalls(draw_list):
            nonlocal dispatch_idx, fsr_count
            
            for draw in draw_list:
                # Only process compute dispatches
                if draw.flags & renderdoc.DrawFlags.Dispatch:
                    dispatch_idx += 1
                    
                    # Get shader reflection
                    pipe = controller.GetPipelineState()
                    cs = pipe.GetShaderReflection(renderdoc.ShaderStage.Compute)
                    
                    shader_name = ""
                    if cs:
                        shader_name = cs.debugInfo.entryFunc if hasattr(cs.debugInfo, 'entryFunc') else ""
                        if not shader_name and hasattr(cs.debugInfo, 'entry'):
                            shader_name = cs.debugInfo.entry
                    
                    # Identify FSR pass
                    pass_name, pass_category = identify_fsr_pass(shader_name)
                    is_fsr = pass_name is not None
                    
                    dispatch_info = {
                        "index": dispatch_idx,
                        "eid": draw.eventId,
                        "shader_name": shader_name,
                        "is_fsr": is_fsr,
                        "pass_name": pass_name,
                        "pass_category": pass_category,
                        "dispatch_dimensions": {
                            "threadgroups_x": draw.dispatchDimension[0] if hasattr(draw, 'dispatchDimension') else None,
                            "threadgroups_y": draw.dispatchDimension[1] if hasattr(draw, 'dispatchDimension') else None,
                            "threadgroups_z": draw.dispatchDimension[2] if hasattr(draw, 'dispatchDimension') else None,
                        },
                    }
                    
                    # Extract resource bindings for FSR passes
                    if is_fsr:
                        fsr_count += 1
                        bindings = {"cbuffers": {}, "srvs": {}, "uavs": {}}
                        
                        # Cbuffers (up to 8 slots)
                        for slot in range(8):
                            cb_data = extract_cbuffer_data(pipe, slot)
                            if cb_data:
                                bindings["cbuffers"][str(slot)] = cb_data
                        
                        # SRVs (up to 32 slots)
                        for slot in range(32):
                            srv_data = extract_descriptor_data(controller, pipe, slot, "SRV")
                            if srv_data:
                                bindings["srvs"][str(slot)] = srv_data
                        
                        # UAVs (up to 16 slots)
                        for slot in range(16):
                            uav_data = extract_descriptor_data(controller, pipe, slot, "UAV")
                            if uav_data:
                                bindings["uavs"][str(slot)] = uav_data
                        
                        dispatch_info["bindings"] = bindings
                        
                        # Thread group dimensions from shader reflection
                        if cs and hasattr(cs, 'dispatchThreadsDimension'):
                            dispatch_info["shader_thread_group_size"] = list(cs.dispatchThreadsDimension)
                        
                        results["fsr_dispatches"].append(dispatch_info)
                    else:
                        # Still log non-FSR compute dispatches for context
                        results["all_compute_dispatches"].append({
                            "index": dispatch_idx,
                            "eid": draw.eventId,
                            "shader_name": shader_name,
                        })
                
                # Recurse into children
                if draw.children:
                    process_drawcalls(draw.children)
        
        process_drawcalls(drawcalls)
        
        # Summary
        results["summary"] = {
            "total_compute_dispatches": dispatch_idx,
            "fsr_dispatches_found": fsr_count,
            "non_fsr_compute": dispatch_idx - fsr_count,
            "expected_fsr_passes": 27,
            "all_passes_found": fsr_count >= 27,
        }
        
        # Save
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n{'='*60}")
        print(f"RESULTS")
        print(f"{'='*60}")
        print(f"Total compute dispatches: {dispatch_idx}")
        print(f"FSR dispatches found: {fsr_count}")
        print(f"Expected: 27")
        print(f"Match: {'YES ✓' if fsr_count >= 27 else 'NO — partial capture or FSR not active'}")
        print(f"\nOutput saved to: {OUTPUT_FILE}")
        
        # Print FSR pass list
        if results["fsr_dispatches"]:
            print(f"\nFSR Passes Detected:")
            for d in results["fsr_dispatches"]:
                dims = d.get("dispatch_dimensions", {})
                tg = f"{dims.get('threadgroups_x', '?')}x{dims.get('threadgroups_y', '?')}x{dims.get('threadgroups_z', '?')}"
                print(f"  {d['pass_name']:20s} [{d['pass_category']:10s}] TG={tg}")
        
        controller.Shutdown()
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        if controller:
            controller.Shutdown()

# ===== RUN =====
# To use: Replace the filename below with your .rdc file path
# Then run this entire script in RenderDoc's Python Shell

CAPTURE_FILE = r"C:\Users\YOUR_USERNAME\Desktop\fsr4-capture-1.rdc"
# ^^^ CHANGE THIS PATH ^^^

if __name__ == "__main__":
    if os.path.exists(CAPTURE_FILE):
        analyze_capture(CAPTURE_FILE)
    else:
        print(f"File not found: {CAPTURE_FILE}")
        print("Edit the CAPTURE_FILE variable at the bottom of this script")
        print("to point to your .rdc file, then run again.")
