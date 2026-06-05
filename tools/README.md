# FSR4 Capture Tools

> ⚠️ **Legal notice**: These tools intercept GPU API calls at runtime. While API hooking is a well-established technique used by debuggers and performance overlays, its legal status may vary by jurisdiction. These tools are provided for research purposes. See [LEGAL.md](../LEGAL.md) for the full legal considerations.

Two capture tools for resolving FSR4 runtime dispatch and buffer bindings.

## Tool 1: FFX Proxy Shim (`ffx_capture_proxy.c`)

Intercepts the 5 exported FFX API functions. Logs function parameters and
raw byte dumps of configuration/dispatch descriptors.

**Build:**
```bash
x86_64-w64-mingw32-gcc -shared -o ffx_proxy.dll ffx_capture_proxy.c \
  -lkernel32 -luser32 -Wl,--out-implib,libffx_proxy.a
```

**Usage:**
1. Install mingw: `sudo pacman -S mingw-w64-gcc`
2. Rename original `dll_v410.dll` to `dll_v410_real.dll`
3. Place compiled `ffx_proxy.dll` as `dll_v410.dll` in the same directory
4. Run the game
5. Check `ffx_capture.log` in the game directory

**What it captures:**
- ffxConfigure: configuration parameters (quality preset, etc.)
- ffxCreateContext: backend interface function pointers, initialization params
- ffxDispatch: per-frame dispatch descriptor (raw bytes)
- ffxDestroyContext: teardown

**Limitation:** Captures at the FFX API level, not the D3D12 level. Can see
dispatch parameters but not the actual GPU resource bindings.

## Tool 2: D3D12 Command List Hook (`ffx_d3d12_capture.c`)

Hooks `ID3D12GraphicsCommandList` to intercept ALL compute dispatch calls.
Logs pipeline state changes, root descriptor table bindings, constant buffer
views, and dispatch dimensions. This is the definitive capture.

**Build:**
```bash
x86_64-w64-mingw32-gcc -shared -o d3d12.dll ffx_d3d12_capture.c \
  -ld3d12 -lkernel32 -ldxgi -lole32 -Wl,--out-implib,libdx12_capture.a
```

**Usage:**
1. Install mingw: `sudo pacman -S mingw-w64-gcc`
2. In the game directory, rename `d3d12.dll` to `d3d12_orig.dll`
3. Place compiled `d3d12.dll` (our hook) in the game directory
4. Optionally set `DX12_CAPTURE_LOG=/path/to/log.txt`
5. Run the game with FSR4 enabled
6. Check `dx12_capture.log` for per-pass binding data

**What it captures:**
- Every `SetPipelineState` with PSO debug name (identifies the shader pass)
- Every `SetComputeRootDescriptorTable` with root parameter index and GPU handle
- Every `SetComputeRootConstantBufferView` with root parameter index and GPU address
- Every `SetComputeRoot32BitConstants` with constant values
- Every `Dispatch` with thread group dimensions
- Filtered to FSR4-relevant passes (checks PSO name for "fsr4", "pass", "model", "mlsr")

**Output format:**
```
[PSO] fsr4_model_v07_fp8_no_scale_pass1
    [BIND] RootParam=0 GPUHandle=0x1a000000100
    [BIND] RootParam=1 GPUHandle=0x1a000000200
    [CBV] RootParam=2 GPUAddr=0x1a000003000
    [CONST] RootParam=3 count=4 offset=0 vals=[0x100,0x80,0x0,0x1]
    [DISPATCH] groups=(2160,1,1) threads=(69120,1,1) total=69120
```

**How to analyze:**
The GPU descriptor handles and addresses can be matched across passes:
- If pass 9's SRV binding (RootParam=X) has the SAME GPU address as pass 1's
  UAV binding, that's a skip connection.
- If all passes bind different addresses, it's sequential.

**⚠️ Status**: These tools were written during the analysis phase but were **not deployed**. The findings in `docs/` are based on static analysis only. Deploying these tools and capturing actual runtime data would strengthen (or contradict) the static analysis conclusions.

## Prerequisites

```bash
# On CachyOS (requires sudo):
sudo pacman -S mingw-w64-gcc

# Verify:
x86_64-w64-mingw32-gcc --version
```
