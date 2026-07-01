#!/usr/bin/env python3
import ctypes
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIB = ROOT / 'libfsr_data_test.so'
EXPECTED_MD5 = {
    'quality': '6ccdb68fc828e0bef93fa32fd144c4f6',
    'drs': '8e5c042e0c14cca83d56ed13df5f02dd',
}
EXPECTED_SHA256 = {
    'quality': 'ce1bd5f19d4fc14f857c5fc810def7f45d5a935a62aa2ca5b5a59829a1d6c868',
    'drs': '101d91f69e3f6121c2a6eb477ee5cbf6e7bf25f26b65c0a4dcd1ac04e57fe2e8',
}

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

    for preset, expected_md5 in EXPECTED_MD5.items():
        entry = lib.fsr_data_find_blob(preset.encode('utf-8'))
        if not entry:
            raise SystemExit(f'fsr_data_find_blob({preset!r}) returned NULL')
        size = entry.contents.size.contents.value
        data = ctypes.string_at(entry.contents.data, size)
        got_md5 = hashlib.md5(data).hexdigest()
        got_sha256 = hashlib.sha256(data).hexdigest()
        print(f'{preset}: size={size} md5={got_md5} sha256={got_sha256}')
        if got_md5 != expected_md5:
            raise SystemExit(f'{preset}: md5 mismatch {got_md5} != {expected_md5}')
        if got_sha256 != EXPECTED_SHA256[preset]:
            raise SystemExit(f'{preset}: sha256 mismatch {got_sha256} != {EXPECTED_SHA256[preset]}')

    print('blob lookup mapping verified')
    return 0


if __name__ == '__main__':
    sys.exit(main())
