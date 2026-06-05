/*
 * ffx_capture_proxy.c — FSR4 DLL Proxy Shim
 * 
 * Intercepts ffxDispatch to log per-pass resource bindings.
 * Compiled as a Windows DLL with mingw-w64-gcc.
 * 
 * Usage:
 *   1. Rename original dll_v410.dll to dll_v410_real.dll
 *   2. Place this proxy as dll_v410.dll in the same directory
 *   3. Run the game — capture log written to ffx_capture.log
 *
 * Build:
 *   x86_64-w64-mingw32-gcc -shared -o dll_v410.dll ffx_capture_proxy.c \
 *     -lkernel32 -luser32 -Wl,--out-implib,libffx_proxy.a
 */

#include <windows.h>
#include <stdio.h>
#include <stdint.h>

/* FFX API types (from open-source FFX SDK) */
typedef enum {
    FFX_API_RETURN_OK = 0,
    FFX_API_RETURN_ERROR = 1,
} FfxApiReturn;

typedef struct {
    uint32_t type;
    void*    ptr;
} FfxApiHeader;

/* Backend interface function pointer types */
typedef FfxApiReturn (*FfxCreateResourceFunc)(void* backend, void* desc, void** resource);
typedef FfxApiReturn (*FfxCreatePipelineFunc)(void* backend, void* desc, void** pipeline);
typedef FfxApiReturn (*FfxStagePipelineFunc)(void* backend, void* cmdList, void* pipeline);
typedef FfxApiReturn (*FfxDispatchFunc)(void* backend, void* cmdList, void* dispatchDesc);
typedef FfxApiReturn (*FfxBarrierFunc)(void* backend, void* cmdList, void* resource);

/* Our state */
static HMODULE g_realDll = NULL;
static FILE* g_logFile = NULL;
static CRITICAL_SECTION g_logCS;
static uint32_t g_dispatchCount = 0;
static uint32_t g_passIndex = 0;

/* Function pointers to real DLL */
typedef FfxApiReturn (*FfxConfigureFunc)(FfxApiHeader*);
typedef FfxApiReturn (*FfxCreateContextFunc)(void**, const FfxApiHeader*);
typedef FfxApiReturn (*FfxDestroyContextFunc)(void*);
typedef FfxApiReturn (*FfxDispatchFunc_)(void*, const FfxApiHeader*);
typedef FfxApiReturn (*FfxQueryFunc)(FfxApiHeader*, FfxApiHeader*);

static FfxConfigureFunc g_realConfigure = NULL;
static FfxCreateContextFunc g_realCreateContext = NULL;
static FfxDestroyContextFunc g_realDestroyContext = NULL;
static FfxDispatchFunc_ g_realDispatch = NULL;
static FfxQueryFunc g_realQuery = NULL;

static void Log(const char* fmt, ...) {
    if (!g_logFile) return;
    EnterCriticalSection(&g_logCS);
    va_list args;
    va_start(args, fmt);
    vfprintf(g_logFile, fmt, args);
    va_end(args);
    fflush(g_logFile);
    LeaveCriticalSection(&g_logCS);
}

/* Hooked backend dispatch — this is where we intercept resource binding */
static FfxApiReturn HookedBackendDispatch(void* backend, void* cmdList, void* dispatchDesc) {
    g_passIndex++;
    
    /* Log the dispatch call with stack trace info */
    Log("[DISPATCH] frame=%u pass=%u cmdList=%p dispatchDesc=%p\n",
        g_dispatchCount, g_passIndex, cmdList, dispatchDesc);
    
    /* 
     * The dispatchDesc contains the pipeline state and resource bindings.
     * In FFX, this typically has:
     *   - Pipeline state object (which shader pass)
     *   - Root descriptor table entries (what buffers are bound)
     *   - Dispatch dimensions (X, Y, Z thread groups)
     *
     * We dump the first 256 bytes of the dispatch desc to capture all binding info.
     */
    if (dispatchDesc) {
        uint8_t* bytes = (uint8_t*)dispatchDesc;
        Log("  dispatchDesc bytes (first 256):\n    ");
        for (int i = 0; i < 256; i++) {
            Log("%02x ", bytes[i]);
            if ((i + 1) % 32 == 0) Log("\n    ");
        }
        Log("\n");
        
        /* Try to extract common D3D12 dispatch dimensions */
        /* D3D12_DISPATCH_ARGUMENTS: {uint32_t ThreadGroupCountX, Y, Z} */
        /* These might be at various offsets depending on the wrapper */
    }
    
    /* Call the original backend dispatch */
    /* We need to get the original function pointer somehow — stored in the context */
    /* For now, we'll capture at the ffxDispatch level instead */
    
    return FFX_API_RETURN_OK;
}

/* Exported functions — proxy to real DLL with logging */

__attribute__((dllexport))
FfxApiReturn ffxConfigure(FfxApiHeader* desc) {
    Log("[CONFIGURE] type=%u ptr=%p\n", desc ? desc->type : 0, desc ? desc->ptr : NULL);
    
    if (desc && desc->ptr) {
        uint8_t* bytes = (uint8_t*)desc->ptr;
        Log("  config data (first 128 bytes):\n    ");
        for (int i = 0; i < 128; i++) {
            Log("%02x ", bytes[i]);
            if ((i + 1) % 32 == 0) Log("\n    ");
        }
        Log("\n");
    }
    
    if (g_realConfigure) return g_realConfigure(desc);
    return FFX_API_RETURN_OK;
}

__attribute__((dllexport))
FfxApiReturn ffxCreateContext(void** context, const FfxApiHeader* desc) {
    Log("[CREATE_CONTEXT] context=%p desc=%p\n", context, desc);
    
    if (desc && desc->ptr) {
        uint8_t* bytes = (uint8_t*)desc->ptr;
        Log("  context desc (first 256 bytes):\n    ");
        for (int i = 0; i < 256; i++) {
            Log("%02x ", bytes[i]);
            if ((i + 1) % 32 == 0) Log("\n    ");
        }
        Log("\n");
        
        /* The context desc contains the backend interface function pointers.
         * These are the key hooking points:
         *   - backend->fpCreateResource
         *   - backend->fpCreatePipeline  
         *   - backend->fpStagePipeline (binds resources to pipeline)
         *   - backend->fpDispatch (executes compute shader)
         *   - backend->fpBarrier
         *
         * We log these pointers so we can identify the binding functions.
         */
    }
    
    FfxApiReturn ret = FFX_API_RETURN_ERROR;
    if (g_realCreateContext) ret = g_realCreateContext(context, desc);
    
    Log("[CREATE_CONTEXT] result=%d context=%p\n", ret, context ? *context : NULL);
    return ret;
}

__attribute__((dllexport))
FfxApiReturn ffxDestroyContext(void* context) {
    Log("[DESTROY_CONTEXT] context=%p\n", context);
    if (g_realDestroyContext) return g_realDestroyContext(context);
    return FFX_API_RETURN_OK;
}

__attribute__((dllexport))
FfxApiReturn ffxDispatch(void* context, const FfxApiHeader* desc) {
    g_dispatchCount++;
    g_passIndex = 0;
    
    Log("\n[DISPATCH] === Frame %u === context=%p desc=%p\n", 
        g_dispatchCount, context, desc);
    
    if (desc && desc->ptr) {
        uint8_t* bytes = (uint8_t*)desc->ptr;
        Log("  dispatch desc (first 256 bytes):\n    ");
        for (int i = 0; i < 256; i++) {
            Log("%02x ", bytes[i]);
            if ((i + 1) % 32 == 0) Log("\n    ");
        }
        Log("\n");
    }
    
    FfxApiReturn ret = FFX_API_RETURN_ERROR;
    if (g_realDispatch) ret = g_realDispatch(context, desc);
    
    Log("[DISPATCH] frame=%u result=%d\n\n", g_dispatchCount, ret);
    return ret;
}

__attribute__((dllexport))
FfxApiReturn ffxQuery(FfxApiHeader* inout, FfxApiHeader* desc) {
    if (g_realQuery) return g_realQuery(inout, desc);
    return FFX_API_RETURN_OK;
}

/* DLL entry point */
BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    switch (fdwReason) {
        case DLL_PROCESS_ATTACH: {
            InitializeCriticalSection(&g_logCS);
            
            /* Open log file in game directory */
            char logPath[MAX_PATH];
            GetModuleFileNameA(NULL, logPath, MAX_PATH);
            char* lastSlash = strrchr(logPath, '\\');
            if (lastSlash) {
                strcpy(lastSlash + 1, "ffx_capture.log");
            } else {
                strcpy(logPath, "ffx_capture.log");
            }
            
            g_logFile = fopen(logPath, "w");
            if (g_logFile) {
                Log("=== FSR4 FFX Capture Proxy v1.0 ===\n");
                Log("Game: %s\n", logPath);
            }
            
            /* Load the real DLL */
            char dllPath[MAX_PATH];
            GetModuleFileNameA((HMODULE)hinstDLL, dllPath, MAX_PATH);
            char* slash = strrchr(dllPath, '\\');
            if (slash) {
                strcpy(slash + 1, "dll_v410_real.dll");
            }
            
            g_realDll = LoadLibraryA(dllPath);
            if (g_realDll) {
                g_realConfigure = (FfxConfigureFunc)GetProcAddress(g_realDll, "ffxConfigure");
                g_realCreateContext = (FfxCreateContextFunc)GetProcAddress(g_realDll, "ffxCreateContext");
                g_realDestroyContext = (FfxDestroyContextFunc)GetProcAddress(g_realDll, "ffxDestroyContext");
                g_realDispatch = (FfxDispatchFunc_)GetProcAddress(g_realDll, "ffxDispatch");
                g_realQuery = (FfxQueryFunc)GetProcAddress(g_realDll, "ffxQuery");
                
                Log("Real DLL loaded: %s\n", dllPath);
                Log("  ffxConfigure=%p\n", g_realConfigure);
                Log("  ffxCreateContext=%p\n", g_realCreateContext);
                Log("  ffxDestroyContext=%p\n", g_realDestroyContext);
                Log("  ffxDispatch=%p\n", g_realDispatch);
                Log("  ffxQuery=%p\n", g_realQuery);
            } else {
                Log("ERROR: Could not load real DLL: %s\n", dllPath);
            }
            
            DisableThreadLibraryCalls((HMODULE)hinstDLL);
            break;
        }
        
        case DLL_PROCESS_DETACH: {
            if (g_logFile) {
                Log("\n=== Capture complete. %u frames, %u total passes ===\n",
                    g_dispatchCount, g_passIndex);
                fclose(g_logFile);
            }
            if (g_realDll) FreeLibrary(g_realDll);
            DeleteCriticalSection(&g_logCS);
            break;
        }
    }
    return TRUE;
}
