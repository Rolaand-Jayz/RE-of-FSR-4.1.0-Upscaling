# Data DLL Rebuild and Section Comparison

This directory contains the pipeline for rebuilding `fsr_data.dll` (FSR 4.1.0) from reverse-engineered source and extracted weight blobs, then comparing the rebuilt file against the original by section.

**Important correction:** a previous version described a bit-identical proof. That was overstated. The old post-link patcher copied original section bodies, headers, and overlay bytes into the output before comparing hashes, which made MD5 equality circular. The current tooling does not patch original bytes into the rebuilt file; it emits a comparison report instead.

## The Three-Step Check

| Step | Tool | Description |
|------|------|-------------|
| **1. Disassemble** | IDA / Ghidra | Reverse the original DLL to recover API logic, data layout, and section structure |
| **2. Rebuild** | MinGW GCC | Compile reconstructed C source + extracted weight blobs into a new DLL |
| **3. Compare** | `pe_patcher.py` | Report per-region hashes and byte differences without modifying rebuilt output |

## Build Prerequisites

- **MinGW GCC** (`x86_64-w64-mingw32-gcc`) — cross-compiler targeting 64-bit Windows
- **Python 3** — for the PE comparison tool
- **Extracted weight blobs** in `../extracted/v410_initializers/`

## Step-by-Step Build Instructions

### 1. Compile the reconstructed DLL

```bash
chmod +x build.sh
./build.sh
```

This produces `fsr_data_prepatch.dll` — the independently rebuilt DLL.

### 2. Compare against the original without patching

```bash
ORIGINAL_DLL=/path/to/original/fsr_data.dll python3 pe_patcher.py --rebuilt fsr_data_prepatch.dll
```

This produces `section-comparison.json`. It does **not** produce or claim a patched bit-identical DLL.

### 3. Interpret the report

```bash
jq '.all_regions_match_without_patching, .regions[] | {region, matches, differing_bytes, first_difference}' section-comparison.json
```

### 4. Verify quality/DRS lookup names against blob hashes

```bash
python3 test_blob_lookup.py
```

## Historical MD5 Hashes

| File | MD5 | Size | Description |
|------|-----|------|-------------|
| `fsr_data_prepatch.dll` | `cddca9acec4e79776cb180d2ee337dc6` | 893,019 bytes | GCC output from RE'd source + extracted blobs |
| `fsr_data_final.dll` | `cb1aa61c71c33b25549ed59c1551d661` | 893,388 bytes | Historical patched artifact; not independent proof |
| **Original** | `cb1aa61c71c33b25549ed59c1551d661` | 893,388 bytes | AMD binary hash |

The 369-byte size difference between the historical pre-patch and final files came from the original overlay copied into the patched file. Treat that as a diagnostic artifact, not evidence of independent reconstruction.

## Weight Blobs

All blobs are located in `../extracted/v410_initializers/`:

| Blob | Size | MD5 | SHA-256 |
|------|------|-----|---------|
| `quality.bin` | 131,072 bytes | `6ccdb68fc828e0bef93fa32fd144c4f6` | `ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868` |
| `balanced.bin` | 131,072 bytes | `6ccdb68fc828e0bef93fa32fd144c4f6` | `ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868` |
| `performance.bin` | 131,072 bytes | `6ccdb68fc828e0bef93fa32fd144c4f6` | `ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868` |
| `ultraperf.bin` | 131,072 bytes | `6ccdb68fc828e0bef93fa32fd144c4f6` | `ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868` |
| `native.bin` | 131,072 bytes | `6ccdb68fc828e0bef93fa32fd144c4f6` | `ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868` |
| `drs.bin` | 131,072 bytes | `8e5c042e0c14cca83d56ed13df5f02dd` | `101d91f69e3f6121c2a6eb477ee5cbf6e7bf25f26b65c0a4dcd1ac04e57fe2e8` |

Five quality-mode blobs share identical content (131,072 bytes of identical weights), while the DRS blob is distinct.

## Reconstructed API Functions

The following exported functions were recovered from disassembly of the original DLL:

| Function | Signature | Behavior |
|----------|-----------|----------|
| `fsr_data_version` | `int (void)` | Returns `0x40100` (version 4.1.0) |
| `fsr_data_blob_count` | `int (void)` | Returns `6` |
| `fsr_data_blob_size` | `int (int idx)` | Returns `0x20000` (131,072) — constant for all indices |
| `fsr_data_get_blob` | `const blob_entry* (unsigned long long idx)` | Returns pointer to indexed `blob_entry` struct, or NULL if out of range |
| `fsr_data_find_blob` | `const blob_entry* (const char* name)` | Linear search over entries by `strcmp` on name field |

The `blob_entry` structure:
```c
struct blob_entry {
    const void* data;          // pointer to weight blob in .data section
    const unsigned int* size;  // pointer to size constant (0x20000) in .rdata
    const char* name;          // quality mode name string in .rdata
};
```

## What the Comparison Tool Does

`pe_patcher.py` is retained for filename compatibility, but it is now a comparison tool. It reports:

1. **PE Headers** — separate SHA-256 hashes and byte differences.

2. **Each section** — separate SHA-256 hashes and byte differences for `.text`, `.rdata`, `.data`, `.pdata`, `.reloc`, exports, and any other section present.

3. **Overlay** — separate SHA-256 hash and byte differences.

No bytes are copied from the original into the rebuilt file. If a region differs, the report says so and the user must decide whether the difference is acceptable for their research purpose.

## File Manifest

| File | Description |
|------|-------------|
| `README.md` | This documentation |
| `fsr_data.c` | Reconstructed C source with inline assembly for data layout |
| `fsr_data.def` | Module definition file controlling exported symbols |
| `pe_patcher.py` | PE section comparison tool; does not patch original bytes into rebuilt output |
| `build.sh` | Build script producing the pre-patch DLL |
| `test_blob_lookup.py` | Verifies that `fsr_data_find_blob("quality")` and `fsr_data_find_blob("drs")` return blobs with the expected MD5/SHA-256 hashes |
