/*
 * ffx_d3d12_capture.c — D3D12 Command List Hook for FSR4
 * 
 * This is the real capture tool. It hooks ID3D12GraphicsCommandList to
 * intercept SetComputeRootDescriptorTable, SetPipelineState, and Dispatch
 * calls. This reveals:
 *   - Which pipeline state (shader pass) is active
 *   - What GPU resources are bound to each root parameter
 *   - The dispatch dimensions per pass
 *
 * Build:
 *   x86_64-w64-mingw32-gcc -shared -o dx12_capture.dll ffx_d3d12_capture.c \
 *     -ld3d12 -lkernel32 -ldxgi -lole32 -Wl,--out-implib,libdx12_capture.a
 *
 * Usage:
 *   Set environment variable DX12_CAPTURE_LOG=filepath before launching game
 *   Or just let it write to dx12_capture.log in the working directory
 */

#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d12.h>
#include <dxgi.h>
#include <stdio.h>
#include <stdint.h>

/* ============================================================
 * Hook infrastructure — vtable patching for ID3D12GraphicsCommandList
 * ============================================================ */

static FILE* g_log = NULL;
static CRITICAL_SECTION g_cs;
static uint32_t g_frameCount = 0;
static uint32_t g_drawCount = 0;
static int g_inCapture = 0;

/* Saved original vtable entries */
static void* g_origSetComputeRootSignature = NULL;
static void* g_origSetPipelineState = NULL;
static void* g_origSetComputeRootDescriptorTable = NULL;
static void* g_origSetComputeRootConstantBufferView = NULL;
static void* g_origSetComputeRoot32BitConstants = NULL;
static void* g_origDispatch = NULL;
static void* g_origClose = NULL;
static void* g_origReset = NULL;

/* Track current pass state */
typedef struct {
    ID3D12PipelineState* pso;
    ID3D12RootSignature* rootSig;
    D3D12_GPU_DESCRIPTOR_HANDLE descriptorTable[16];
    D3D12_GPU_VIRTUAL_ADDRESS cbv[16];
    uint32_t constants[64];
    uint32_t threadGroups[3];
    int hasDispatch;
} PassState;

static PassState g_currentPass = {0};

static void Log(const char* fmt, ...) {
    if (!g_log) return;
    EnterCriticalSection(&g_cs);
    va_list args;
    va_start(args, fmt);
    vfprintf(g_log, fmt, args);
    va_end(args);
    fflush(g_log);
    LeaveCriticalSection(&g_cs);
}

/* Try to identify FSR4 shaders by PSO name */
static const char* GetPSOName(ID3D12PipelineState* pso) {
    if (!pso) return "NULL";
    
    /* Query the debug name */
    static char nameBuf[256];
    UINT size = 0;
    HRESULT hr = ID3D12PipelineState_GetPrivateData(
        pso, &WKPDID_D3DDebugObjectNameW, &size, NULL);
    
    if (size > 0 && size < sizeof(nameBuf)) {
        wchar_t wname[128];
        hr = ID3D12PipelineState_GetPrivateData(
            pso, &WKPDID_D3DDebugObjectNameW, &size, wname);
        if (SUCCEEDED(hr)) {
            WideCharToMultiByte(CP_UTF8, 0, wname, -1, nameBuf, sizeof(nameBuf), NULL, NULL);
            return nameBuf;
        }
    }
    
    /* Try ASCII name */
    hr = ID3D12PipelineState_GetPrivateData(
        pso, &WKPDID_D3DDebugObjectName, &size, NULL);
    if (size > 0 && size < sizeof(nameBuf)) {
        hr = ID3D12PipelineState_GetPrivateData(
            pso, &WKPDID_D3DDebugObjectName, &size, nameBuf);
        if (SUCCEEDED(hr)) {
            nameBuf[size] = 0;
            return nameBuf;
        }
    }
    
    static char addrBuf[32];
    snprintf(addrBuf, sizeof(addrBuf), "%p", (void*)pso);
    return addrBuf;
}

/* ============================================================
 * Hooked command list methods
 * ============================================================ */

/* Forward declarations for the hooked functions */
typedef void (STDMETHODCALLTYPE *SetComputeRootSignature_t)(
    ID3D12GraphicsCommandList*, ID3D12RootSignature*);
typedef HRESULT (STDMETHODCALLTYPE *SetPipelineState_t)(
    ID3D12GraphicsCommandList*, ID3D12PipelineState*);
typedef void (STDMETHODCALLTYPE *SetComputeRootDescriptorTable_t)(
    ID3D12GraphicsCommandList*, UINT, D3D12_GPU_DESCRIPTOR_HANDLE);
typedef void (STDMETHODCALLTYPE *SetComputeRootConstantBufferView_t)(
    ID3D12GraphicsCommandList*, UINT, D3D12_GPU_VIRTUAL_ADDRESS);
typedef void (STDMETHODCALLTYPE *SetComputeRoot32BitConstants_t)(
    ID3D12GraphicsCommandList*, UINT, UINT, const void*, UINT);
typedef void (STDMETHODCALLTYPE *Dispatch_t)(
    ID3D12GraphicsCommandList*, UINT, UINT, UINT);
typedef HRESULT (STDMETHODCALLTYPE *Close_t)(ID3D12GraphicsCommandList*);
typedef HRESULT (STDMETHODCALLTYPE *Reset_t)(
    ID3D12GraphicsCommandList*, ID3D12CommandAllocator*, ID3D12PipelineState*);

static void STDMETHODCALLTYPE HookedSetComputeRootSignature(
    ID3D12GraphicsCommandList* This, ID3D12RootSignature* pRootSignature) {
    g_currentPass.rootSig = pRootSignature;
    SetComputeRootSignature_t orig = (SetComputeRootSignature_t)g_origSetComputeRootSignature;
    orig(This, pRootSignature);
}

static HRESULT STDMETHODCALLTYPE HookedSetPipelineState(
    ID3D12GraphicsCommandList* This, ID3D12PipelineState* pPSO) {
    const char* name = GetPSOName(pPSO);
    
    /* Check if this looks like an FSR4 pass */
    int isFSR = (strstr(name, "fsr4") || strstr(name, "FSR4") || 
                 strstr(name, "pass") || strstr(name, "Pass") ||
                 strstr(name, "prepass") || strstr(name, "postpass") ||
                 strstr(name, "model") || strstr(name, "mlsr"));
    
    if (isFSR) {
        g_currentPass.pso = pPSO;
        g_currentPass.hasDispatch = 0;
        Log("  [PSO] %s\n", name);
    }
    
    SetPipelineState_t orig = (SetPipelineState_t)g_origSetPipelineState;
    return orig(This, pPSO);
}

static void STDMETHODCALLTYPE HookedSetComputeRootDescriptorTable(
    ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
    D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor) {
    
    if (g_currentPass.pso) {
        g_currentPass.descriptorTable[RootParameterIndex] = BaseDescriptor;
        Log("    [BIND] RootParam=%u GPUHandle=0x%llx\n", 
            RootParameterIndex, (unsigned long long)BaseDescriptor.ptr);
    }
    
    SetComputeRootDescriptorTable_t orig = 
        (SetComputeRootDescriptorTable_t)g_origSetComputeRootDescriptorTable;
    orig(This, RootParameterIndex, BaseDescriptor);
}

static void STDMETHODCALLTYPE HookedSetComputeRootConstantBufferView(
    ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
    D3D12_GPU_VIRTUAL_ADDRESS BufferLocation) {
    
    if (g_currentPass.pso) {
        g_currentPass.cbv[RootParameterIndex] = BufferLocation;
        Log("    [CBV] RootParam=%u GPUAddr=0x%llx\n",
            RootParameterIndex, (unsigned long long)BufferLocation);
    }
    
    SetComputeRootConstantBufferView_t orig = 
        (SetComputeRootConstantBufferView_t)g_origSetComputeRootConstantBufferView;
    orig(This, RootParameterIndex, BufferLocation);
}

static void STDMETHODCALLTYPE HookedSetComputeRoot32BitConstants(
    ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
    UINT Num32BitValuesToSet, const void* pSrcData, UINT DestOffsetIn32BitValues) {
    
    if (g_currentPass.pso) {
        const uint32_t* vals = (const uint32_t*)pSrcData;
        Log("    [CONST] RootParam=%u count=%u offset=%u vals=[",
            RootParameterIndex, Num32BitValuesToSet, DestOffsetIn32BitValues);
        for (UINT i = 0; i < Num32BitValuesToSet && i < 8; i++) {
            Log("%s0x%x", i ? "," : "", vals[i]);
        }
        if (Num32BitValuesToSet > 8) Log(",...");
        Log("]\n");
    }
    
    SetComputeRoot32BitConstants_t orig = 
        (SetComputeRoot32BitConstants_t)g_origSetComputeRoot32BitConstants;
    orig(This, RootParameterIndex, Num32BitValuesToSet, pSrcData, DestOffsetIn32BitValues);
}

static void STDMETHODCALLTYPE HookedDispatch(
    ID3D12GraphicsCommandList* This,
    UINT ThreadGroupCountX, UINT ThreadGroupCountY, UINT ThreadGroupCountZ) {
    
    if (g_currentPass.pso) {
        g_drawCount++;
        g_currentPass.threadGroups[0] = ThreadGroupCountX;
        g_currentPass.threadGroups[1] = ThreadGroupCountY;
        g_currentPass.threadGroups[2] = ThreadGroupCountZ;
        g_currentPass.hasDispatch = 1;
        
        Log("    [DISPATCH] groups=(%u,%u,%u) threads=(%u,%u,%u) total=%u\n",
            ThreadGroupCountX, ThreadGroupCountY, ThreadGroupCountZ,
            ThreadGroupCountX * 32, ThreadGroupCountY, ThreadGroupCountZ,
            ThreadGroupCountX * ThreadGroupCountY * ThreadGroupCountZ * 32);
    }
    
    Dispatch_t orig = (Dispatch_t)g_origDispatch;
    orig(This, ThreadGroupCountX, ThreadGroupCountY, ThreadGroupCountZ);
}

static HRESULT STDMETHODCALLTYPE HookedClose(ID3D12GraphicsCommandList* This) {
    if (g_currentPass.pso) {
        /* Flush current pass state */
        g_currentPass.pso = NULL;
        g_currentPass.rootSig = NULL;
        memset(g_currentPass.descriptorTable, 0, sizeof(g_currentPass.descriptorTable));
        memset(g_currentPass.cbv, 0, sizeof(g_currentPass.cbv));
    }
    
    Close_t orig = (Close_t)g_origClose;
    return orig(This);
}

static HRESULT STDMETHODCALLTYPE HookedReset(
    ID3D12GraphicsCommandList* This, 
    ID3D12CommandAllocator* pAllocator, ID3D12PipelineState* pInitialState) {
    
    g_currentPass.pso = NULL;
    g_currentPass.rootSig = NULL;
    
    Reset_t orig = (Reset_t)g_origReset;
    return orig(This, pAllocator, pInitialState);
}

/* ============================================================
 * Vtable patching
 * ============================================================ */

static void PatchCommandList(ID3D12GraphicsCommandList* cmdList) {
    /* The vtable is at *cmdList (pointer to vtable pointer) */
    void** vtable = *(void***)cmdList;
    
    /* ID3D12GraphicsCommandList vtable layout (from d3d12.h):
     * [0]  QueryInterface
     * [1]  AddRef
     * [2]  Release (from IUnknown)
     * [3-8] ID3D12Object methods
     * [9-12] ID3D12DeviceChild methods
     * [13] ID3D12CommandList::GetType
     * [14] Close
     * [15] Reset
     * [16] ClearState
     * [17] DrawInstanced
     * [18] DrawIndexedInstanced
     * [19] Dispatch  <-- KEY
     * [20] CopyBufferRegion
     * ...
     * [26] SetComputeRootSignature
     * [27] SetGraphicsRootSignature
     * [28] SetComputeRootDescriptorTable <-- KEY
     * [29] SetGraphicsRootDescriptorTable
     * [30] SetComputeRootConstantBufferView <-- KEY
     * ...
     * [37] SetPipelineState <-- KEY
     * ...
     * [40] SetComputeRoot32BitConstants <-- KEY
     */
    
    DWORD oldProtect;
    
    /* Make vtable writable */
    VirtualProtect(vtable, 512, PAGE_READWRITE, &oldProtect);
    
    /* Save originals and patch */
    if (!g_origDispatch) {
        g_origDispatch = vtable[19];
        vtable[19] = HookedDispatch;
    }
    
    if (!g_origSetComputeRootSignature) {
        g_origSetComputeRootSignature = vtable[26];
        vtable[26] = HookedSetComputeRootSignature;
    }
    
    if (!g_origSetComputeRootDescriptorTable) {
        g_origSetComputeRootDescriptorTable = vtable[28];
        vtable[28] = HookedSetComputeRootDescriptorTable;
    }
    
    if (!g_origSetComputeRootConstantBufferView) {
        g_origSetComputeRootConstantBufferView = vtable[30];
        vtable[30] = HookedSetComputeRootConstantBufferView;
    }
    
    if (!g_origSetPipelineState) {
        g_origSetPipelineState = vtable[37];
        vtable[37] = HookedSetPipelineState;
    }
    
    if (!g_origSetComputeRoot32BitConstants) {
        g_origSetComputeRoot32BitConstants = vtable[40];
        vtable[40] = HookedSetComputeRoot32BitConstants;
    }
    
    if (!g_origClose) {
        g_origClose = vtable[14];
        vtable[14] = HookedClose;
    }
    
    if (!g_origReset) {
        g_origReset = vtable[15];
        vtable[15] = HookedReset;
    }
    
    VirtualProtect(vtable, 512, oldProtect, &oldProtect);
}

/* ============================================================
 * Hook ID3D12Device::CreateCommandList to patch new command lists
 * ============================================================ */

typedef HRESULT (STDMETHODCALLTYPE *CreateCommandList_t)(
    ID3D12Device*, UINT, D3D12_COMMAND_LIST_TYPE, ID3D12CommandAllocator*,
    ID3D12PipelineState*, REFIID, void**);

static void* g_origCreateCommandList = NULL;

static HRESULT STDMETHODCALLTYPE HookedCreateCommandList(
    ID3D12Device* This, UINT nodeMask, D3D12_COMMAND_LIST_TYPE type,
    ID3D12CommandAllocator* pAllocator, ID3D12PipelineState* pInitialState,
    REFIID riid, void** ppCommandList) {
    
    CreateCommandList_t orig = (CreateCommandList_t)g_origCreateCommandList;
    HRESULT hr = orig(This, nodeMask, type, pAllocator, pInitialState, riid, ppCommandList);
    
    if (SUCCEEDED(hr) && ppCommandList && *ppCommandList) {
        PatchCommandList((ID3D12GraphicsCommandList*)*ppCommandList);
        Log("[HOOK] Patched new command list %p (type=%d)\n", *ppCommandList, type);
    }
    
    return hr;
}

/* Patch the device's CreateCommandList */
static void PatchDevice(ID3D12Device* device) {
    void** vtable = *(void***)device;
    DWORD oldProtect;
    
    /* CreateCommandList is at vtable index 28 in ID3D12Device */
    VirtualProtect(vtable, 512, PAGE_READWRITE, &oldProtect);
    
    if (!g_origCreateCommandList) {
        g_origCreateCommandList = vtable[28];
        vtable[28] = HookedCreateCommandList;
    }
    
    VirtualProtect(vtable, 512, oldProtect, &oldProtect);
    Log("[HOOK] Patched D3D12 device %p\n", device);
}

/* ============================================================
 * Hook D3D12CreateDevice to intercept device creation
 * ============================================================ */

typedef HRESULT (WINAPI *D3D12CreateDevice_t)(
    IUnknown*, D3D_FEATURE_LEVEL, REFIID, void**);

static D3D12CreateDevice_t g_origD3D12CreateDevice = NULL;

HRESULT WINAPI HookedD3D12CreateDevice(
    IUnknown* pAdapter, D3D_FEATURE_LEVEL MinimumFeatureLevel,
    REFIID riid, void** ppDevice) {
    
    Log("[CREATE_DEVICE] adapter=%p featureLevel=%u\n", pAdapter, MinimumFeatureLevel);
    
    HRESULT hr = g_origD3D12CreateDevice(pAdapter, MinimumFeatureLevel, riid, ppDevice);
    
    if (SUCCEEDED(hr) && ppDevice && *ppDevice) {
        PatchDevice((ID3D12Device*)*ppDevice);
    }
    
    return hr;
}

/* ============================================================
 * DLL Entry — hook d3d12.dll
 * ============================================================ */

static HMODULE g_d3d12 = NULL;

/* Export our hooked D3D12CreateDevice as a drop-in replacement */
__attribute__((dllexport))
HRESULT WINAPI D3D12CreateDevice(
    IUnknown* pAdapter, D3D_FEATURE_LEVEL MinimumFeatureLevel,
    REFIID riid, void** ppDevice) {
    return HookedD3D12CreateDevice(pAdapter, MinimumFeatureLevel, riid, ppDevice);
}

__attribute__((dllexport))
HRESULT WINAPI D3D12GetDebugInterface(REFIID riid, void** ppvDebug) {
    if (!g_d3d12) g_d3d12 = LoadLibraryA("d3d12_orig.dll");
    if (g_d3d12) {
        typedef HRESULT (WINAPI *fn_t)(REFIID, void**);
        fn_t fn = (fn_t)GetProcAddress(g_d3d12, "D3D12GetDebugInterface");
        if (fn) return fn(riid, ppvDebug);
    }
    return E_FAIL;
}

__attribute__((dllexport))
HRESULT WINAPI D3D12SerializeRootSignature(
    const D3D12_ROOT_SIGNATURE_DESC* pRootSignature,
    D3D_ROOT_SIGNATURE_VERSION Version, ID3DBlob** ppBlob, ID3DBlob** ppErrorBlob) {
    if (!g_d3d12) g_d3d12 = LoadLibraryA("d3d12_orig.dll");
    if (g_d3d12) {
        typedef HRESULT (WINAPI *fn_t)(const D3D12_ROOT_SIGNATURE_DESC*, D3D_ROOT_SIGNATURE_VERSION, ID3DBlob**, ID3DBlob**);
        fn_t fn = (fn_t)GetProcAddress(g_d3d12, "D3D12SerializeRootSignature");
        if (fn) return fn(pRootSignature, Version, ppBlob, ppErrorBlob);
    }
    return E_FAIL;
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    switch (fdwReason) {
        case DLL_PROCESS_ATTACH: {
            InitializeCriticalSection(&g_cs);
            
            /* Open log */
            const char* logPath = getenv("DX12_CAPTURE_LOG");
            if (!logPath) logPath = "dx12_capture.log";
            g_log = fopen(logPath, "w");
            if (g_log) {
                Log("=== D3D12 FSR4 Capture Hook v1.0 ===\n");
            }
            
            /* Hook D3D12 by loading original d3d12.dll */
            /* This DLL should be named d3d12.dll and placed in the game dir */
            /* The real d3d12.dll should be renamed to d3d12_orig.dll */
            g_d3d12 = LoadLibraryA("d3d12_orig.dll");
            if (g_d3d12) {
                g_origD3D12CreateDevice = (D3D12CreateDevice_t)
                    GetProcAddress(g_d3d12, "D3D12CreateDevice");
                Log("[INIT] Hooked d3d12.dll, original at d3d12_orig.dll\n");
                Log("[INIT] D3D12CreateDevice: orig=%p\n", g_origD3D12CreateDevice);
            } else {
                Log("[ERROR] Could not load d3d12_orig.dll\n");
            }
            
            DisableThreadLibraryCalls((HMODULE)hinstDLL);
            break;
        }
        
        case DLL_PROCESS_DETACH: {
            if (g_log) {
                Log("\n=== Capture done. %u dispatches, %u frames ===\n",
                    g_drawCount, g_frameCount);
                fclose(g_log);
            }
            if (g_d3d12) FreeLibrary(g_d3d12);
            DeleteCriticalSection(&g_cs);
            break;
        }
    }
    return TRUE;
}
