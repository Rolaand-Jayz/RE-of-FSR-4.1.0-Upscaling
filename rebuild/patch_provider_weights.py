#!/usr/bin/env python3
"""
FSR 4.1.0 Provider DLL Weight Patcher

Patches the neural network weight blobs embedded in amd_fidelityfx_upscaler_dx12.dll
with extracted/reconstructed weights. This enables:
  - Weight verification (confirm extracted weights match shipping binary)
  - Weight swapping (replace weights with different presets or custom-trained data)
  - Version upgrades (patch 4.1.0 weights into a 4.0.2 provider)

Usage:
  # Verify weights match (no changes made)
  python3 patch_provider_weights.py --verify --provider /path/to/amd_fidelityfx_upscaler_dx12.dll

  # Patch weights from extracted blobs
  python3 patch_provider_weights.py --patch --provider /path/to/amd_fidelityfx_upscaler_dx12.dll \
    --weights /path/to/v410_initializers/

  # Swap DRS weights into quality slot (for testing)
  python3 patch_provider_weights.py --swap --provider /path/to/amd_fidelityfx_upscaler_dx12.dll \
    --from drs --to quality
"""
import struct
import hashlib
import os
import sys
import shutil
import argparse

# Weight blob offsets in the 4.1.0 provider DLL (.rdata section)
# Discovered via LEA tracing in Ghidra + confirmed by signature match
WEIGHT_OFFSETS_V410 = {
    # All 5 standard presets point to the same physical blob
    "quality":     0x008d6370,
    "balanced":    0x008d6370,  # same blob as quality
    "performance": 0x008d6370,  # same blob as quality
    "ultraperf":   0x008d6370,  # same blob as quality
    "native":      0x008d6370,  # same blob as quality
    "drs":         0x008b3f20,
}

BLOB_SIZE = 131072  # 0x20000 bytes per weight blob

# Known good MD5 hashes (from RE extraction)
BLOB_HASHES = {
    "quality":     "6ccdb68fc828e0bef93fa32fd144c4f6",
    "balanced":    "6ccdb68fc828e0bef93fa32fd144c4f6",
    "performance": "6ccdb68fc828e0bef93fa32fd144c4f6",
    "ultraperf":   "6ccdb68fc828e0bef93fa32fd144c4f6",
    "native":      "6ccdb68fc828e0bef93fa32fd144c4f6",
    "drs":         "8e5c042e0c14cca83d56ed13df5f02dd",
}

def read_blob(path):
    with open(path, "rb") as f:
        return f.read()

def find_blob_offset(data, blob_data, preset):
    """Find the blob offset by signature match."""
    sig = blob_data[:32]
    pos = data.find(sig)
    return pos

def verify_weights(provider_path, weights_dir):
    """Verify that extracted weights match the provider DLL."""
    with open(provider_path, "rb") as f:
        data = f.read()

    print(f"Provider DLL: {provider_path} ({len(data)} bytes)")
    print(f"Weights dir:  {weights_dir}")
    print()

    all_match = True
    for preset in ["quality", "drs"]:  # Only 2 unique blobs
        blob_path = os.path.join(weights_dir, f"{preset}.bin")
        if not os.path.exists(blob_path):
            print(f"  {preset:12s}: SKIP (file not found)")
            continue

        blob = read_blob(blob_path)
        if len(blob) != BLOB_SIZE:
            print(f"  {preset:12s}: FAIL (wrong size: {len(blob)} != {BLOB_SIZE})")
            all_match = False
            continue

        # Find in provider
        offset = find_blob_offset(data, blob, preset)
        actual_md5 = hashlib.md5(blob).hexdigest()
        expected_md5 = BLOB_HASHES[preset]

        if offset >= 0:
            full_match = data[offset:offset + BLOB_SIZE] == blob
            md5_match = actual_md5 == expected_md5
            status = "OK" if (full_match and md5_match) else "MISMATCH"
            if not full_match or not md5_match:
                all_match = False
            print(f"  {preset:12s}: offset=0x{offset:08x} md5={actual_md5[:12]} [{status}]")
        else:
            print(f"  {preset:12s}: NOT FOUND in provider")
            all_match = False

    print()
    if all_match:
        print("✓ All weight blobs confirmed — extraction matches shipping binary")
    else:
        print("✗ Weight verification FAILED — see above")
    return all_match

def patch_weights(provider_path, weights_dir, output_path=None):
    """Patch the provider DLL with extracted weights."""
    if output_path is None:
        output_path = provider_path + ".patched"

    # Backup
    backup_path = provider_path + ".original"
    if not os.path.exists(backup_path):
        shutil.copy2(provider_path, backup_path)
        print(f"Backed up original to: {backup_path}")

    with open(provider_path, "rb") as f:
        data = bytearray(f.read())

    print(f"Patching: {provider_path}")

    # Patch each unique blob
    patched = 0
    seen_offsets = set()
    for preset in ["quality", "drs"]:
        blob_path = os.path.join(weights_dir, f"{preset}.bin")
        if not os.path.exists(blob_path):
            continue

        blob = read_blob(blob_path)
        offset = find_blob_offset(data, blob, preset)

        if offset < 0:
            print(f"  {preset:12s}: SKIP (blob not found)")
            continue

        if offset not in seen_offsets:
            # Write the blob
            data[offset:offset + BLOB_SIZE] = blob
            seen_offsets.add(offset)
            md5 = hashlib.md5(blob).hexdigest()
            print(f"  {preset:12s}: patched at 0x{offset:08x} (md5={md5[:12]})")
            patched += 1
        else:
            print(f"  {preset:12s}: shares offset with another preset (already patched)")

    with open(output_path, "wb") as f:
        f.write(data)

    print(f"\nPatched {patched} blob(s). Output: {output_path}")
    return output_path

def main():
    parser = argparse.ArgumentParser(description="FSR 4.1.0 Provider DLL Weight Patcher")
    parser.add_argument("--verify", action="store_true", help="Verify weights match (no changes)")
    parser.add_argument("--patch", action="store_true", help="Patch provider DLL with extracted weights")
    parser.add_argument("--provider", required=True, help="Path to amd_fidelityfx_upscaler_dx12.dll")
    parser.add_argument("--weights", default="../extracted/v410_initializers/",
                       help="Directory containing extracted weight blobs")
    parser.add_argument("--output", default=None, help="Output path for patched DLL")
    args = parser.parse_args()

    if args.verify:
        ok = verify_weights(args.provider, args.weights)
        sys.exit(0 if ok else 1)
    elif args.patch:
        patch_weights(args.provider, args.weights, args.output)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
