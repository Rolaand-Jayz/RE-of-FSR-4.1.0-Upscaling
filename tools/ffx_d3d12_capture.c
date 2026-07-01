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
 * Build (with compile hardening):
 *   x86_64-w64-mingw32-gcc -Wall -Wextra -Wformat -Werror -shared \
 *     -o dx12_capture.dll ffx_d3d12_capture.c \
 *     -ld3d12 -lkernel32 -ldxgi -lole32 -Wl,--out-implib,libdx12_capture.a
 *
 * Supported compilers: MinGW-w64 GCC 13+ or MSVC 19.37+
 *
 * Usage:
 *   Set environment variable DX12_CAPTURE_LOG=filepath before launching game
 *   Or just let it write to dx12_capture.log in the working directory
 *
 * RESEARCH-GRADE WARNING: This tool is not production-tested. The vtable
 * patching approach is brittle across interface versions, debug layers,
 * and proxy stacks. See tools/README.md for known limitations.
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
 *
 * WARNING: This approach mutates shared/global vtables via VirtualProtect.
 * It is brittle across interface versions, wrapper DLLs, debug layers,
 * and proxy stacks. A more robust approach would use COM wrapper objects
 * (wrap the returned ID3D12GraphicsCommandList and forward all methods
 * while intercepting compute methods) or Detours/MinHook-style function
 * interception. The current approach is research-grade only.
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
#define MAX_ROOT_PARAMS 16
#define MAX_ROOT_CONSTANTS 64

typedef struct {
    ID3D12PipelineState* pso;
    ID3D12RootSignature* rootSig;
    D3D12_GPU_DESCRIPTOR_HANDLE descriptorTable[MAX_ROOT_PARAMS];
    D3D12_GPU_VIRTUAL_ADDRESS cbv[MAX_ROOT_PARAMS];
    uint32_t constants[MAX_ROOT_CONSTANTS];
    uint32_t threadGroups[3];
    int hasDispatch;
    char psoHash[65];  /* SHA-256 hex of CS bytecode, or empty */
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

/* ---- Minimal SHA-256 (public domain) ---- */
typedef struct { uint32_t s[8]; uint64_t len; uint8_t buf[64]; } sha256_ctx;
static const uint32_t sha256_k[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,
    0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
    0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,
    0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
    0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
    0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,
    0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,
    0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
    0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};
#define SHA256_ROTR(x,n) (((x)>>(n))|((x)<<(32-(n))))
#define SHA256_CH(x,y,z) (((x)&(y))^(~(x)&(z)))
#define SHA256_MAJ(x,y,z) (((x)&(y))^((x)&(z))^((y)&(z)))
#define SHA256_EP0(x) (SHA256_ROTR(x,2)^SHA256_ROTR(x,13)^SHA256_ROTR(x,22))
#define SHA256_EP1(x) (SHA256_ROTR(x,6)^SHA256_ROTR(x,11)^SHA256_ROTR(x,25))
#define SHA256_SIG0(x) (SHA256_ROTR(x,7)^SHA256_ROTR(x,18)^((x)>>3))
#define SHA256_SIG1(x) (SHA256_ROTR(x,17)^SHA256_ROTR(x,19)^((x)>>10))
static void sha256_init(sha256_ctx*c){c->len=0;c->s[0]=0x6a09e667;c->s[1]=0xbb67ae85;c->s[2]=0x3c6ef372;c->s[3]=0xa54ff53a;c->s[4]=0x510e527f;c->s[5]=0x9b05688c;c->s[6]=0x1f83d9ab;c->s[7]=0x5be0cd19;}
static void sha256_block(sha256_ctx*c,const uint8_t*p){
    uint32_t w[64],a,b,cc,d,e,f,g,h,t1,t2;int i;
    for(i=0;i<16;i++)w[i]=((uint32_t)p[i*4]<<24)|((uint32_t)p[i*4+1]<<16)|((uint32_t)p[i*4+2]<<8)|p[i*4+3];
    for(;i<64;i++)w[i]=SHA256_SIG1(w[i-2])+w[i-7]+SHA256_SIG0(w[i-15])+w[i-16];
    a=c->s[0];b=c->s[1];cc=c->s[2];d=c->s[3];e=c->s[4];f=c->s[5];g=c->s[6];h=c->s[7];
    for(i=0;i<64;i++){t1=h+SHA256_EP1(e)+SHA256_CH(e,f,g)+sha256_k[i]+w[i];t2=SHA256_EP0(a)+SHA256_MAJ(a,b,cc);h=g;g=f;f=e;e=d+t1;d=cc;cc=b;b=a;a=t1+t2;}
    c->s[0]+=a;c->s[1]+=b;c->s[2]+=cc;c->s[3]+=d;c->s[4]+=e;c->s[5]+=f;c->s[6]+=g;c->s[7]+=h;
}
static void sha256_update(sha256_ctx*c,const uint8_t*d,size_t n){size_t i;for(i=0;i<n;i++){c->buf[c->len&63]=d[i];c->len++;if(!(c->len&63))sha256_block(c,c->buf);}}
static void sha256_final(sha256_ctx*c,uint8_t*out){uint64_t bits=c->len*8;uint32_t i=c->len&63;c->buf[i++]=0x80;if(i>56){while(i<64)c->buf[i++]=0;sha256_block(c,c->buf);i=0;}while(i<56)c->buf[i++]=0;for(int j=7;j>=0;j--)c->buf[i++]=(uint8_t)(bits>>(j*8));sha256_block(c,c->buf);for(i=0;i<8;i++){out[i*4]=c->s[i]>>24;out[i*4+1]=c->s[i]>>16;out[i*4+2]=c->s[i]>>8;out[i*4+3]=c->s[i];}}
static void sha256_hex(const uint8_t*hash,char*out){const char*h="0123456789abcdef";for(int i=0;i<32;i++){out[i*2]=h[hash[i]>>4];out[i*2+1]=h[hash[i]&0xf];}out[64]=0;}

/*
 * Extract CS bytecode from a pipeline state and compute SHA-256.
 * This identifies PSOs even when debug names are absent (common in
 * optimized retail builds). Falls back to PSO pointer if extraction fails.
 */
static void GetPSOHash(ID3D12PipelineState* pso, char* out, size_t outsz) {
    out[0] = 0;
    if (!pso) return;

    /* Try to get the cached blob (contains the serialized PSO including bytecode) */
    ID3DBlob* blob = NULL;
    HRESULT hr = ID3D12PipelineState_GetCachedBlob(pso, &blob);
    if (SUCCEEDED(hr) && blob) {
        size_t sz = ID3DBlob_GetBufferSize(blob);
        const uint8_t* data = (const uint8_t*)ID3DBlob_GetBufferPointer(blob);
        if (sz > 0 && data) {
            sha256_ctx ctx;
            uint8_t hash[32];
            sha256_init(&ctx);
            sha256_update(&ctx, data, sz);
            sha256_final(&ctx, hash);
            sha256_hex(hash, out);
        }
        ID3DBlob_Release(blob);
    }

    /* If we couldn't get the blob, fall back to pointer-based identity */
    if (out[0] == 0) {
        snprintf(out, outsz, "ptr_%p", (void*)pso);
    }
}

/* ============================================================
 * Descriptor identity tracking — map GPU handles to resources
 *
 * To fully resolve SRV/UAV identity from descriptor handles, the
 * following device methods must also be hooked (on the device vtable
 * after D3D12CreateDevice returns):
 *   - CreateShaderResourceView  (ID3D12Device vtable index ~32)
 *   - CreateUnorderedAccessView (index ~33)
 *   - CopyDescriptors           (index ~41)
 *   - CopyDescriptorsSimple     (index ~42)
 *
 * The hooked versions should record: { CPU descriptor handle, resource
 * pointer, view desc fields } so that later, when a command list binds
 * a descriptor table, the GPU handle range can be resolved back to the
 * underlying resource objects.
 *
 * Additionally, ID3D12GraphicsCommandList::SetDescriptorHeaps (vtable
 * index ~24) must be hooked to track which descriptor heaps are active
 * on the command list, so that CPU-handle→resource lookups can be done.
 *
 * These hooks are documented but not yet implemented below. The current
 * capture logs GPU descriptor handle values but does NOT resolve them to
 * resource IDs. This is a known limitation.
 * ============================================================ */

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
        g_currentPass.psoHash[0] = 0;
        GetPSOHash(pPSO, g_currentPass.psoHash, sizeof(g_currentPass.psoHash));
        Log("  [PSO] name=%s sha256=%s\n", name, g_currentPass.psoHash);
    }
    
    SetPipelineState_t orig = (SetPipelineState_t)g_origSetPipelineState;
    return orig(This, pPSO);
}

static void STDMETHODCALLTYPE HookedSetComputeRootDescriptorTable(
    ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
    D3D12_GPU_DESCRIPTOR_HANDLE BaseDescriptor) {
    
    if (g_currentPass.pso) {
        if (RootParameterIndex < MAX_ROOT_PARAMS) {
            g_currentPass.descriptorTable[RootParameterIndex] = BaseDescriptor;
            Log("    [BIND] RootParam=%u GPUHandle=0x%llx\n", 
                RootParameterIndex, (unsigned long long)BaseDescriptor.ptr);
        } else {
            Log("[WARN] root param overflow: RootParamIndex=%u >= %d\n", RootParameterIndex, MAX_ROOT_PARAMS);
        }
    }
    
    SetComputeRootDescriptorTable_t orig = 
        (SetComputeRootDescriptorTable_t)g_origSetComputeRootDescriptorTable;
    orig(This, RootParameterIndex, BaseDescriptor);
}

static void STDMETHODCALLTYPE HookedSetComputeRootConstantBufferView(
    ID3D12GraphicsCommandList* This, UINT RootParameterIndex,
    D3D12_GPU_VIRTUAL_ADDRESS BufferLocation) {
    
    if (g_currentPass.pso) {
        if (RootParameterIndex < MAX_ROOT_PARAMS) {
            g_currentPass.cbv[RootParameterIndex] = BufferLocation;
            Log("    [CBV] RootParam=%u GPUAddr=0x%llx\n",
                RootParameterIndex, (unsigned long long)BufferLocation);
        } else {
            Log("[WARN] root param overflow: RootParamIndex=%u >= %d (CBV)\n", RootParameterIndex, MAX_ROOT_PARAMS);
        }
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
        UINT endIdx = DestOffsetIn32BitValues + Num32BitValuesToSet;
        if (endIdx <= MAX_ROOT_CONSTANTS) {
            for (UINT i = 0; i < Num32BitValuesToSet; i++) {
                g_currentPass.constants[DestOffsetIn32BitValues + i] = vals[i];
            }
        } else {
            Log("[WARN] root constants overflow: offset=%u count=%u end=%u >= %d\n",
                DestOffsetIn32BitValues, Num32BitValuesToSet, endIdx, MAX_ROOT_CONSTANTS);
        }
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

/*
 * Attempt to read CBV upload buffer contents for logging.
 * This maps each CBV GPU virtual address and dumps up to 128 bytes.
 * Wrapped in SEH for safety — buffer may be write-only or inaccessible.
 * NOTE: Full CBV content capture requires tracking resource creation to
 * build a GPU-VA → ID3D12Resource map. This stub logs the intent; the
 * full implementation is documented in runtime-validation/schema.json.
 */
static void LogCBVContents(void) {
    for (UINT i = 0; i < MAX_ROOT_PARAMS; i++) {
        if (g_currentPass.cbv[i] == 0) continue;
        /* TODO: resolve GPU VA to ID3D12Resource, Map for reading, dump 128 bytes.
         * Current limitation: we log the address but cannot read contents without
         * the resource-creation hooks described in the descriptor identity section. */
        Log("    [CBV_DATA] RootParam=%u GPUAddr=0x%llx (contents: UNRESOLVED — requires descriptor/resource hooks)\n",
            i, (unsigned long long)g_currentPass.cbv[i]);
    }
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
        
        /* Log CBV contents for this dispatch (currently UNRESOLVED — see LogCBVContents) */
        LogCBVContents();
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
