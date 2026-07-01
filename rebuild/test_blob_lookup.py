#!/usr/bin/env python3
"""
Test fsr_data_find_blob for correctness across all presets,
invalid inputs, and edge cases.

Verifies:
  - All 6 presets return the correct blob data
  - quality/balanced/performance/ultraperf/native share the same hash
  - drs returns a distinct hash
  - Invalid preset names return NULL
  - NULL pointer input returns NULL (tested via ctypes NULL pointer)
  - All blobs are exactly 131072 bytes
"""
import ctypes
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIB = ROOT / 'libfsr_data_test.so'

# Known hashes from committed extracted blobs
EXPECTED_MD5 = {
    'quality':     '6ccdb68fc828e0bef93fa32fd144c4f6',
    'balanced':    '6ccdb68fc828e0bef93fa32fd144c4f6',
    'performance': '6ccdb68fc828e0bef93fa32fd144c4f6',
    'ultraperf':   '6ccdb68fc828e0bef93fa32fd144c4f6',
    'native':      '6ccdb68fc828e0bef93fa32fd144c4f6',
    'drs':         '8e5c042e0c14cca83d56ed13df5f02dd',
}
EXPECTED_SHA256 = {
    'quality':     'ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868',
    'balanced':    'ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868',
    'performance': 'ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868',
    'ultraperf':   'ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868',
    'native':      'ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868',
    'drs':         '101d91f69e3f6121c2a6eb477ee5cbf6e7bf25f26b65c0a4dcd1ac04e57fe2e8',
}
BLOB_SIZE = 131072
STANDARD_PRESETS = ['quality', 'balanced', 'performance', 'ultraperf', 'native']
DRS_PRESET = 'drs'

class BlobEntry(ctypes.Structure):
    _fields_ = [
        ('data', ctypes.c_void_p),
        ('size', ctypes.POINTER(ctypes.c_uint)),
        ('name', ctypes.c_char_p),
    ]


def build_shared_library() -> None:
    cmd = ['gcc', '-shared', '-fPIC', '-O2', '-o', str(LIB), 'fsr_data.c']
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    build_shared_library()
    lib = ctypes.CDLL(str(LIB))
    lib.fsr_data_find_blob.argtypes = [ctypes.c_char_p]
    lib.fsr_data_find_blob.restype = ctypes.POINTER(BlobEntry)

    errors = 0

    # --- Test 1: All presets return correct data ---
    print('--- Test 1: All preset lookups ---')
    for preset in list(EXPECTED_MD5.keys()):
        entry = lib.fsr_data_find_blob(preset.encode('utf-8'))
        if not entry:
            print(f'  FAIL: fsr_data_find_blob({preset!r}) returned NULL')
            errors += 1
            continue
        size = entry.contents.size.contents.value
        data = ctypes.string_at(entry.contents.data, size)
        got_md5 = hashlib.md5(data).hexdigest()
        got_sha256 = hashlib.sha256(data).hexdigest()
        status = 'OK' if got_md5 == EXPECTED_MD5[preset] else 'FAIL'
        print(f'  [{status}] {preset}: size={size} md5={got_md5}')
        if got_md5 != EXPECTED_MD5[preset]:
            print(f'    expected md5={EXPECTED_MD5[preset]}')
            errors += 1
        if got_sha256 != EXPECTED_SHA256[preset]:
            print(f'    FAIL: sha256 mismatch')
            errors += 1
        if size != BLOB_SIZE:
            print(f'    FAIL: size={size} expected={BLOB_SIZE}')
            errors += 1

    # --- Test 2: Standard presets share identical weights ---
    print('--- Test 2: Standard presets share identical weights ---')
    hashes = {}
    for preset in STANDARD_PRESETS:
        entry = lib.fsr_data_find_blob(preset.encode('utf-8'))
        if not entry:
            print(f'  FAIL: {preset} returned NULL')
            errors += 1
            continue
        size = entry.contents.size.contents.value
        data = ctypes.string_at(entry.contents.data, size)
        hashes[preset] = hashlib.md5(data).hexdigest()
    unique_std = set(hashes.values())
    if len(unique_std) == 1:
        print(f'  OK: all 5 standard presets share md5={unique_std.pop()}')
    else:
        print(f'  FAIL: standard presets have {len(unique_std)} distinct hashes')
        errors += 1

    # --- Test 3: DRS is distinct from standard ---
    print('--- Test 3: DRS preset is distinct ---')
    drs_entry = lib.fsr_data_find_blob(DRS_PRESET.encode('utf-8'))
    if drs_entry:
        drs_size = drs_entry.contents.size.contents.value
        drs_data = ctypes.string_at(drs_entry.contents.data, drs_size)
        drs_hash = hashlib.md5(drs_data).hexdigest()
        if drs_hash != list(hashes.values())[0]:
            print(f'  OK: drs md5={drs_hash} is distinct from standard')
        else:
            print(f'  FAIL: drs hash matches standard presets')
            errors += 1
    else:
        print(f'  FAIL: drs returned NULL')
        errors += 1

    # --- Test 4: Invalid preset returns NULL ---
    print('--- Test 4: Invalid preset names ---')
    invalid_names = ['unknown', 'QUALITY', 'Quality', 'drs_v2', 'pass1', 'nullpreset']
    for name in invalid_names:
        entry = lib.fsr_data_find_blob(name.encode('utf-8'))
        if entry:
            print(f'  FAIL: invalid name {name!r} returned non-NULL')
            errors += 1
        else:
            print(f'  OK: {name!r} returned NULL as expected')

    # --- Test 5: Empty string ---
    print('--- Test 5: Empty string input ---')
    entry = lib.fsr_data_find_blob(b'')
    if entry:
        print(f'  FAIL: empty string returned non-NULL')
        errors += 1
    else:
        print(f'  OK: empty string returned NULL')

    # --- Test 6: NULL pointer input ---
    print('--- Test 6: NULL pointer input ---')
    entry = lib.fsr_data_find_blob(None)
    if entry:
        print(f'  FAIL: NULL pointer returned non-NULL')
        errors += 1
    else:
        print(f'  OK: NULL pointer returned NULL')

    # --- Summary ---
    print()
    if errors == 0:
        print('All blob lookup tests passed')
        return 0
    else:
        print(f'{errors} test failure(s)')
        return 1


if __name__ == '__main__':
    sys.exit(main())
