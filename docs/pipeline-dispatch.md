# FSR 4.1.0 Main DLL Analysis: Pipeline Dispatch & Shader Mapping

## Executive Summary

We traced the static dispatch pipeline of `amd_fidelityfx_upscaler_dx12.dll` (15.6MB) from binary analysis:
- **30 unique shader blobs** confirmed by MD5 hash
- **27-pass main loop** + 3 conditional passes (RCAS, SPD AutoExposure, Debug View)
- **Thread groups**: All passes use (32, 1, 1) — wavefront-width dispatch
- **Resource binding map**: 9 register spaces identified with semantic meaning
- **CBV layout**: 5-6 registers per pass (80-96 bytes), even/odd pass pair pattern
- **FUN_180025990** decoded via raw x86-64 disassembly (not decompilable by Ghidra)

## Pipeline Architecture

### Dispatch Function (FUN_18000d5b0)
```
lVar24 = 0x1b;  // 27
do {
    dispatch_per_pass(context, pass_state, threadsX, threadsY);
    lVar24--;
} while (lVar24 != 0);
```
Then conditionally: RCAS → SPD AutoExposure → Debug View

### PSO Creation Function (FUN_180025990)
Ghidra failed to decompile this function. We disassembled it from raw binary:

1. **Jump table** at RVA `0x2acac`: 30 entries dispatching to per-pass code paths
2. **Flag index table** at RVA `0x1bfc50`: 64 entries mapping config flags to descriptor indices (0-29)
3. **Pass descriptor table** at RVA `0x115cf0`, stride `0x128` (296 bytes), 30 entries
4. Each entry: shader blob (DXBC/DXIL) + 7 binding groups of 40 bytes each

### Pass Descriptor Structure (296 bytes)
```
offset  size  description
0x00     4     shader blob size
0x04     4     padding
0x08     8     shader blob pointer (DXBC)
0x10     40    binding group 0 (count + 4 pointers)
0x38     40    binding group 1 (count + 4 pointers)
0x60     40    binding group 2 (count + 4 pointers)
0x88     40    binding group 3 (count + 4 pointers)
0xb0     40    binding group 4 (count + 4 pointers)
0xd8     40    binding group 5 (count + 4 pointers)
0x100    40    binding group 6 (always count=0)
```

## Shader Blob Verification

All 30 blobs verified unique by MD5 hash:

| Pass | Name | Blob RVA | Size | MD5 (truncated) |
|------|------|----------|------|------------------|
| 0 | pass_0 | 0x13a1e0 | 19820 | fa813b1501c7 |
| 1 | pass_1 | 0x7d9820 | 19884 | 98e3a4b72437 |
| 2 | pass_2 | 0x0d64c0 | 21648 | d99b11628f3b |
| 3 | pass_3 | 0x8a3ee0 | 21584 | 76fdac8ca3c1 |
| 4 | pass_4 | 0x143dd0 | 23336 | abb9cec4c47d |
| 5 | pass_5 | 0x60c6b0 | 26276 | cb3ad940c94a |
| 6 | pass_6 | 0x232520 | 23404 | 37998fc070d8 |
| 7 | pass_7 | 0x0602b0 | 26208 | 6859bda414df |
| 8 | pass_8 | 0x290090 | 21740 | a52c653d1f5c |
| 9 | pass_9 | 0x551190 | 21676 | 564efec2abd2 |
| 10 | pass_10 | 0x889190 | 24856 | 4a85f5300bf4 |
| 11 | pass_11 | 0x7370f0 | 24788 | 0114b73c945c |
| 12 | pass_12 | 0x6feac0 | 21984 | 33e2e5c24e0d |
| 13 | pass_13 | 0x844680 | 21920 | c287b4976479 |
| 14 | pass_14 | 0x546c80 | 18500 | 8b335e65c091 |
| 15 | pass_15 | 0x3c4980 | 18436 | 3829ef86bf37 |
| 16 | pass_16 | 0x23e8f0 | 20456 | 3fbb8b9bd3ad |
| 17 | pass_17 | 0x73e140 | 20388 | e144590c77dd |
| 18 | pass_18 | 0x7b95d0 | 20552 | 7756f6dd0508 |
| 19 | pass_19 | 0x79a4b0 | 20480 | aeaf1b44d0b2 |
| 20 | pass_20 | 0x077780 | 26276 | 4d61c10addc6 |
| 21 | pass_21 | 0x2a67f0 | 26208 | c12ca5dfa20c |
| 22 | pass_22 | 0x0fc260 | 23404 | c6930a995aab |
| 23 | pass_23 | 0x3becf0 | 19884 | 5943b34bd00e |
| 24 | pass_24 | 0x5e4b70 | 19820 | a00a487f3be2 |
| 25 | pass_25 | 0x769230 | 23336 | 7e95f96376a7 |
| 26 | pass_26 | 0x78ee90 | 21648 | f1079dce7c99 |
| 27 | rcas | 0x4d66f0 | 21584 | 5c6397e93889 |
| 28 | spd_autoexposure | 0x5e9a50 | 21740 | 1f4a33f858b4 |
| 29 | debug_view | 0x295580 | 21676 | 4bf4d0a6886c |

**Unique: 30/30, Duplicates: 0**

## Resource Binding Map

All passes use identical UAV layout:
- **UAV reg 0, space 11**: Scratch buffer (resolution-dependent)
- **UAV reg 1, space 0**: Output color
- **UAV reg 2, space 3**: Temp/recurrent output

All passes use identical CBV/Sampler:
- **CBV reg 0, space 1**: Constant buffer (5-6 registers × 4 floats)
- **Sampler reg 0, space 0**: Point clamp sampler

SRV layout varies by pass (5-8 SRVs):

| Space | Name | Present In |
|-------|------|------------|
| 18 | Neural weights | All passes |
| 0 | Input color | All passes |
| 1 | Motion/reprojection | All passes |
| 2 | Luma/mask | Most passes (not 10-15) |
| 3 | History/temporal | All passes |
| 4 | Exposure/luma mip | All passes |
| 6 | Feature extra | Passes 8,9,18,19,28,29 |
| 17 | Intermediate | Passes with 7+ SRVs |

## Constant Buffer Layout

Each cbuffer register is 4 × float32 = 16 bytes:

| Reg | Even passes (pre) | Odd passes (post) |
|-----|-------------------|---------------------|
| 0 | ✓ dispatch dims | ✓ dispatch dims |
| 1 | ✓ jitter/offset | ✓ jitter/offset |
| 2 | ✓ scale/transform | ✓ scale/transform |
| 3 | — | ✓ extra params |
| 4 | ✓ config | ✓ config |
| 5 | ✓ config | ✓ config |

- Even passes: 5 regs × 16B = **80 bytes**
- Odd passes: 6 regs × 16B = **96 bytes**

## Pass Pair Structure

The 27 main passes form 12 pairs + 1 standalone:
- Passes 0,1 = pair 0 (pre/post)
- Passes 2,3 = pair 1 (pre/post)
- ...
- Passes 24,25 = pair 12 (pre/post)
- Pass 26 = standalone final pass

Odd passes (post) access CBV register 3, which even passes (pre) skip.

## Pass Symmetry

Blobs with identical sizes suggest architectural symmetry:
- pass_0 ↔ pass_24 (19820 bytes)
- pass_1 ↔ pass_23 (19884 bytes)
- pass_4 ↔ pass_25 (23336 bytes)
- pass_5 ↔ pass_20 (26276 bytes)
- pass_6 ↔ pass_22 (23404 bytes)
- pass_7 ↔ pass_21 (26208 bytes)

This is consistent with an autoencoder architecture with symmetric encoder/decoder channel progressions.

## Binding Group Counts

Per-pass descriptor binding group sizes (group 1 varies):

| Passes | Group 1 Count | SRVs |
|--------|---------------|------|
| 10-15 | 4 | 5 |
| 0,1,4-7,16,17,20-25 | 5 | 6 |
| 2,3,18,19,26,27 | 6 | 7 |
| 8,9,28,29 | 7 | 8 |

## What We Did NOT Verify

1. **Constant buffer field semantics** — we know which registers are accessed but not the exact meaning of each float
2. **Root signature binary layout** — the binding groups in the descriptor entry are FFX-internal structures, not raw D3D12_ROOT_PARAMETER
3. **Runtime verification** — game requires Proton, all capture methods fail
4. **Shader internals** — we mapped resources but didn't decode the ML inference operations within each shader

## Methodology

1. Ghidra decompilation of 344 exported/internal functions
2. Raw x86-64 disassembly of FUN_180025990 (Ghidra couldn't decompile)
3. PE section parsing to locate data tables by RVA
4. DXBC container parsing to extract DXIL shaders
5. LLVM IR analysis (602 blobs from dxc -dxil-dis)
6. Resource binding extraction from createHandle/cbufferLoadLegacy patterns
7. Cross-referenced Ghidra decompilation with binary analysis for verification
