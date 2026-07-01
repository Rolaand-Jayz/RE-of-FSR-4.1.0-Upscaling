#!/usr/bin/env python3
"""
DEPRECATED -- use compare_sections.py instead.

This file is kept for historical reference only. The original
pe_patcher.py copied original PE section bytes, headers, and overlay
into the rebuilt DLL before comparing hashes, making the resulting MD5
equality circular. It has been moved to _archive/pe_patcher_historical.py.

The current comparison tool is compare_sections.py, which:
  - Compares rebuilt sections against the original
  - Emits a per-region diff report
  - Does NOT copy any original bytes into the rebuilt output
  - Does NOT claim bit-identical reconstruction
"""
import sys
sys.exit("pe_patcher.py is deprecated. Use: python compare_sections.py --rebuilt <dll>")
