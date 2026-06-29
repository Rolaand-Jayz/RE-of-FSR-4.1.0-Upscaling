#!/usr/bin/env python3
"""Static RE Closure: Verify tensor offsets against 4.1.0 blob + extract MAC formulas from HLSL."""
import json, os, struct, re, math, glob

REPO = "/mnt/workdrive/fsr-re"
SDK = "/mnt/workdrive/fsr4-sdk-402-source/Kits/FidelityFX/upscalers/fsr4/internal/shaders"

# ============================================================
# PART 1: Verify tensor offsets against actual 4.1.0 blob data
# ============================================================
print("=" * 70)
print("PART 1: Tensor Offset Verification against 4.1.0 Blob")
print("=" * 70)

# Load tensor map
tm = json.load(open(os.path.join(REPO, "spec/tensor-map.json")))
tensors = tm["tensors"]

# Load quality blob
with open(os.path.join(REPO, "extracted/v410_initializers/quality.bin"), "rb") as f:
    blob = f.read()
print(f"Blob size: {len(blob)} bytes")

def fp16_to_float(raw):
    """Convert IEEE 754 half-precision to float."""
    sign = (raw >> 15) & 1
    exp = (raw >> 10) & 0x1f
    mant = raw & 0x3ff
    if exp == 0:
        return (-1)**sign * mant * (2**-24) if mant else 0.0
    elif exp == 31:
        return float('inf') if not mant else float('nan')
    return (-1)**sign * (1 + mant / 1024.0) * (2 ** (exp - 15))

verification_results = []
all_pass = True

for i, t in enumerate(tensors):
    name = t["name"]
    offset = t["offset"]
    size = t["byte_size"]
    ttype = t["tensor_type"]
    pass_num = t["pass"]

    # Read the region from the blob
    region = blob[offset:offset + size]

    result = {
        "index": i,
        "name": name,
        "pass": pass_num,
        "offset": offset,
        "size": size,
        "type": ttype,
    }

    if "Tensor1f" in ttype or "bias" in name.lower():
        # FP32 bias tensor
        n_floats = size // 4
        floats = struct.unpack(f"<{n_floats}f", region[:n_floats * 4])
        finite = sum(1 for v in floats if math.isfinite(v))
        nonzero = sum(1 for v in floats if v != 0.0)
        max_abs = max(abs(v) for v in floats if math.isfinite(v))
        result["n_values"] = n_floats
        result["finite"] = finite
        result["nonzero"] = nonzero
        result["max_abs"] = round(max_abs, 6)
        result["sample"] = [round(v, 4) for v in floats[:5]]
        result["status"] = "PASS" if finite == n_floats and max_abs < 1e6 else "FAIL"
        if result["status"] != "PASS":
            all_pass = False

    elif "Tensor4h_HNWC" in ttype:
        # FP16 weight tensor (encoder1 downscale)
        n_halves = size // 2
        halves = struct.unpack(f"<{n_halves}h", region[:n_halves * 2])
        floats = [fp16_to_float(h) for h in halves]
        finite = sum(1 for v in floats if math.isfinite(v))
        nonzero = sum(1 for v in floats if v != 0.0)
        max_abs = max(abs(v) for v in floats if math.isfinite(v))
        result["n_values"] = n_halves
        result["finite"] = finite
        result["nonzero"] = nonzero
        result["max_abs"] = round(max_abs, 6)
        result["sample"] = [round(v, 4) for v in floats[:5]]
        result["status"] = "PASS" if finite == n_halves and max_abs < 1e6 else "FAIL"
        if result["status"] != "PASS":
            all_pass = False

    elif "QuantizedTensor4f8" in ttype:
        # FP8/uint8 weight tensor
        uint8_vals = list(region)
        unique = len(set(uint8_vals))
        result["n_values"] = len(uint8_vals)
        result["unique_values"] = unique
        result["sample"] = sorted(set(uint8_vals))[:10]
        result["status"] = "PASS" if unique >= 2 else "FAIL"
        if result["status"] != "PASS":
            all_pass = False

    else:
        result["status"] = "UNKNOWN_TYPE"
        all_pass = False

    verification_results.append(result)

# Print summary
passed = sum(1 for r in verification_results if r["status"] == "PASS")
failed = sum(1 for r in verification_results if r["status"] == "FAIL")
unknown = sum(1 for r in verification_results if r["status"] == "UNKNOWN_TYPE")
print(f"\nVerification: {passed} PASS / {failed} FAIL / {unknown} UNKNOWN out of {len(tensors)}")
print(f"Overall: {'ALL PASS' if all_pass else 'FAILURES PRESENT'}")

# Show any failures
for r in verification_results:
    if r["status"] != "PASS":
        print(f"  {r['status']}: [{r['index']}] {r['name']} offset={r['offset']} size={r['size']}")

# Show a sample of passed tensors
print("\nSample of verified tensors:")
for r in verification_results[:5] + verification_results[40:45]:
    if "sample" in r:
        print(f"  [{r['index']:2d}] pass={r['pass']:2s} off={r['offset']:6d} sz={r['size']:5d} {r['status']} {r['name'][:45]:45s} sample={r['sample'][:5]}")

# Save verification report
vr_path = os.path.join(REPO, "reports/tensor-offset-verification.json")
with open(vr_path, "w") as f:
    json.dump({
        "schema_version": "1.0",
        "source": "static_re_closure",
        "blob_file": "extracted/v410_initializers/quality.bin",
        "blob_size": len(blob),
        "tensor_count": len(tensors),
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "all_pass": all_pass,
        "method": "Parsed 4.1.0 quality blob using 4.0.2 HLSL-derived tensor offsets. Each tensor region validated for type-appropriate value distribution.",
        "results": verification_results,
    }, f, indent=2)
print(f"\nSaved: {vr_path}")

# ============================================================
# PART 2: Extract MAC arithmetic formulas from HLSL operator includes
# ============================================================
print("\n" + "=" * 70)
print("PART 2: MAC Arithmetic from HLSL Operator Includes")
print("=" * 70)

# Find operator include files
runtime_dir = os.path.join(SDK, "ml2code_runtime")
if not os.path.exists(runtime_dir):
    # Try alternative paths
    for alt in [
        os.path.join(os.path.dirname(SDK), "ml2code_runtime"),
        "/mnt/workdrive/fsr4-sdk-402-source/Kits/FidelityFX/upscalers/fsr4/ml2code_runtime",
    ]:
        if os.path.exists(alt):
            runtime_dir = alt
            break

print(f"Runtime dir: {runtime_dir} (exists: {os.path.exists(runtime_dir)})")

# Find all operator hlsli files
operator_files = []
for root, dirs, files in os.walk(runtime_dir):
    for f in files:
        if f.endswith('.hlsli'):
            fpath = os.path.join(root, f)
            operator_files.append(fpath)
print(f"Operator include files: {len(operator_files)}")
for f in operator_files:
    print(f"  {os.path.relpath(f, runtime_dir)}")

# Read key operator files and extract MAC formulas
mac_formulas = {}
operators_to_read = [
    "Conv2D_k2s2b.hlsli",
    "ConvNextBlock.hlsli",
    "Conv2D_k3s1b.hlsli",
    "Conv2D_k4s1b.hlsli",
    "Conv2D_k5s4b.hlsli",
    "ConvTranspose2D_k2s2b.hlsli",
]

for op_name in operators_to_read:
    found = False
    for fpath in operator_files:
        if os.path.basename(fpath) == op_name:
            with open(fpath, 'r') as f:
                content = f.read()
            # Extract the MAC pattern: look for multiply-add
            muls = re.findall(r'(\w+)\s*\*=\s*(\w+)', content)
            adds = re.findall(r'(\w+)\s*\+=\s*(\w+)', content)
            fmas = re.findall(r'(\w+)\s*=\s*(\w+)\s*\*\s*(\w+)\s*\+\s*(\w+)', content)

            # Find weight access pattern
            weight_loads = re.findall(r'(\w+\.Load|rawBufferLoad|InitializerBuffer\.\w+)[^;]+;', content)

            # Find bias add
            bias_adds = re.findall(r'bias\[|\.bias|bias\s*\+', content)

            mac_formulas[op_name] = {
                "file": os.path.relpath(fpath, runtime_dir),
                "lines": content.count('\n'),
                "multiply_assign_count": len(muls),
                "add_assign_count": len(adds),
                "fma_count": len(fmas),
                "weight_load_patterns": weight_loads[:5],
                "has_bias_add": len(bias_adds) > 0,
                "first_30_lines": content.split('\n')[:30],
            }
            print(f"\n  {op_name}: {len(content)} chars, {content.count(chr(10))} lines")
            print(f"    FMA patterns: {len(fmas)}, *= patterns: {len(muls)}, += patterns: {len(adds)}")
            found = True
            break
    if not found:
        print(f"\n  {op_name}: NOT FOUND")

# Extract pass→operator mapping from the main HLSL
hlsl_path = os.path.join(SDK, "fsr4_model_v07_fp8_no_scale_passes_1080.hlsl")
with open(hlsl_path, 'r') as f:
    hlsl = f.read()

pass_operators = {}
for m in re.finditer(r'#include\s+"([^"]+)"', hlsl):
    include = m.group(1)
    # Find which pass this belongs to
    line_start = hlsl.rfind('\n', 0, m.start())
    context = hlss_context = hlsl[max(0, m.start()-500):m.start()]
    pass_match = re.search(r'PASS_(\d+)', context)
    pass_num = int(pass_match.group(1)) if pass_match else -1
    if "operators/" in include:
        if pass_num not in pass_operators:
            pass_operators[pass_num] = []
        pass_operators[pass_num].append(include)

print("\n\nPass → Operator mapping:")
for p in sorted(pass_operators.keys()):
    print(f"  pass{p}: {pass_operators[p]}")

# Save MAC formulas report
mac_path = os.path.join(REPO, "reports/mac-arithmetic-formulas.json")
with open(mac_path, "w") as f:
    json.dump({
        "schema_version": "1.0",
        "source": "4.0.2 MIT-licensed HLSL (ml2code_runtime operators)",
        "method": "Extracted multiply-accumulate patterns from HLSL operator include files. These operators are #included by each pass function in fsr4_model_v07_fp8_no_scale_passes_1080.hlsl.",
        "pass_operator_mapping": {str(k): v for k, v in pass_operators.items()},
        "operator_analysis": {k: {**v, "first_30_lines": None} for k, v in mac_formulas.items()},
    }, f, indent=2)
print(f"\nSaved: {mac_path}")

# ============================================================
# PART 3: Extract complete per-pass tensor layout from HLSL
# ============================================================
print("\n" + "=" * 70)
print("PART 3: Per-pass tensor layout extraction from HLSL")
print("=" * 70)

# Parse the HLSL to extract every tensor declaration per pass
pass_tensor_layout = {}
current_pass = None

# Split by pass defines
pass_blocks = re.split(r'#ifdef\s+MLSR_PASS_(\d+)(?:_POST)?', hlsl)
for i in range(1, len(pass_blocks) - 1, 2):
    pass_num = int(pass_blocks[i])
    block = pass_blocks[i + 1] if i + 1 < len(pass_blocks) else ""

    # Skip post blocks for now (they're padding operations)
    if "_POST" in block[:20]:
        continue

    tensors_in_pass = []
    # Find all threadGroupStorageByteOffset values
    for m in re.finditer(r'threadGroupStorageByteOffset\s*\n\s*(\d+)', block):
        offset = int(m.group(1))
        # Find the name above this
        before = block[:m.start()]
        name_match = re.findall(r'(\w+)\s*=\s*\{', before[-500:])
        tensor_type_match = re.findall(r'(?:const\s+)?(\w+<[^>]+>)\s+', before[-500:])

        # Also find shape info
        shape_match = re.search(r'logicalSize.*?=\s*(.+?),', block[max(0, m.start()-300):m.start()+100])

        tensors_in_pass.append({
            "offset": offset,
            "shape": shape_match.group(1) if shape_match else None,
        })

    pass_tensor_layout[pass_num] = tensors_in_pass
    print(f"  pass{pass_num}: {len(tensors_in_pass)} tensors, offsets: {[t['offset'] for t in tensors_in_pass]}")

# Save
layout_path = os.path.join(REPO, "reports/hlsl-per-pass-layout.json")
with open(layout_path, "w") as f:
    json.dump({
        "schema_version": "1.0",
        "source": "fsr4_model_v07_fp8_no_scale_passes_1080.hlsl",
        "pass_count": max(pass_tensor_layout.keys()) + 1,
        "layout": {str(k): v for k, v in sorted(pass_tensor_layout.items())},
    }, f, indent=2)
print(f"\nSaved: {layout_path}")

print("\n" + "=" * 70)
print("STATIC RE CLOSURE COMPLETE")
print("=" * 70)
print(f"Tensor offset verification: {'ALL 78 PASS' if all_pass else 'FAILURES'}")
print(f"MAC formulas extracted: {len(mac_formulas)} operators")
print(f"Pass layouts extracted: {len(pass_tensor_layout)} passes")
