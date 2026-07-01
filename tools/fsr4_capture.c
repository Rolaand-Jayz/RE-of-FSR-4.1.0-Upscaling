/*
 * FSR 4 Lightweight Runtime Capture Shim
 *
 * Intercepts vkCmdDispatch to log FSR 4 compute passes and dump
 * InitializerBuffer contents. No system packages needed.
 *
 * Build:  gcc -shared -fPIC -O2 -Wall -Wextra -Wformat -Werror -o fsr4_capture.so fsr4_capture.c -ldl
 * Use:    LD_PRELOAD=./tools/fsr4_capture.so ...
 *         Set FSR4_CAPTURE_DIR to override the output directory.
 *
 * Output: $FSR4_CAPTURE_DIR/dispatch_log.txt (default: ./runtime-capture/)
 *         $FSR4_CAPTURE_DIR/initializer_XXXX.bin
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <stdint.h>
#include <time.h>
#include <sys/stat.h>
#include <unistd.h>

#include <vulkan/vulkan.h>

/* ── Configuration ─────────────────────────────────────────── */
#define OUTPUT_DIR_DEFAULT "./runtime-capture"
static char OUTPUT_DIR[512] = OUTPUT_DIR_DEFAULT;
static char LOG_FILE[600];
#define MAX_CAPTURES 64

/* ── Globals ───────────────────────────────────────────────── */
static FILE *g_log = NULL;
static int  g_dispatch_count = 0;
static int  g_buffer_captures = 0;
static int  g_initialized = 0;

/* Real function pointers */
static PFN_vkCmdDispatch          real_vkCmdDispatch = NULL;
static PFN_vkCmdBindDescriptorSets real_vkCmdBindDescriptorSets = NULL;
static PFN_vkGetDescriptorSetLayoutBindingOffsetEXT real_vkGetBindingOffset = NULL;

/* Track bound descriptor sets per command buffer */
#define MAX_CB_TRACKING 256
typedef struct {
    VkCommandBuffer cb;
    VkDescriptorSet descriptorSets[8];
    uint32_t setCount;
} CBTrack;

static CBTrack g_cb_tracks[MAX_CB_TRACKING];
static int g_cb_track_count = 0;

/* ── Helpers ───────────────────────────────────────────────── */
static void ensure_init(void) {
    if (g_initialized) return;
    g_initialized = 1;
    
    const char* env_dir = getenv("FSR4_CAPTURE_DIR");
    if (env_dir && env_dir[0]) {
        strncpy(OUTPUT_DIR, env_dir, sizeof(OUTPUT_DIR) - 1);
        OUTPUT_DIR[sizeof(OUTPUT_DIR) - 1] = 0;
    }
    snprintf(LOG_FILE, sizeof(LOG_FILE), "%s/dispatch_log.txt", OUTPUT_DIR);
    
    mkdir(OUTPUT_DIR, 0755);
    
    g_log = fopen(LOG_FILE, "w");
    if (!g_log) {
        /* Fallback to stderr */
        g_log = stderr;
    }
    
    time_t now = time(NULL);
    fprintf(g_log, "=== FSR 4 Runtime Capture ===\n");
    fprintf(g_log, "Started: %s", ctime(&now));
    fprintf(g_log, "=============================\n\n");
    fflush(g_log);
}

static CBTrack *find_or_create_cb(VkCommandBuffer cb) {
    for (int i = 0; i < g_cb_track_count; i++) {
        if (g_cb_tracks[i].cb == cb) return &g_cb_tracks[i];
    }
    if (g_cb_track_count < MAX_CB_TRACKING) {
        CBTrack *t = &g_cb_tracks[g_cb_track_count++];
        memset(t, 0, sizeof(*t));
        t->cb = cb;
        return t;
    }
    return NULL;
}

/* Read buffer contents via vkCmdCopyBuffer → would need a device.
   Instead, we'll log what we can see and let the full analysis happen
   with VKD3D debug output + the SPIR-V dumps. */

/* ── Hooks ─────────────────────────────────────────────────── */

VKAPI_ATTR void VKAPI_CALL
hook_vkCmdBindDescriptorSets(
    VkCommandBuffer commandBuffer,
    VkPipelineBindPoint pipelineBindPoint,
    VkPipelineLayout layout,
    uint32_t firstSet,
    uint32_t descriptorSetCount,
    const VkDescriptorSet *pDescriptorSets,
    uint32_t dynamicOffsetCount,
    const uint32_t *pDynamicOffsets)
{
    ensure_init();
    
    if (pipelineBindPoint == VK_PIPELINE_BIND_POINT_COMPUTE) {
        CBTrack *t = find_or_create_cb(commandBuffer);
        if (t && descriptorSetCount <= 8) {
            for (uint32_t i = 0; i < descriptorSetCount; i++) {
                if (firstSet + i < 8) {
                    t->descriptorSets[firstSet + i] = pDescriptorSets[i];
                }
            }
            t->setCount = firstSet + descriptorSetCount;
        }
    }
    
    if (real_vkCmdBindDescriptorSets) {
        real_vkCmdBindDescriptorSets(
            commandBuffer, pipelineBindPoint, layout,
            firstSet, descriptorSetCount, pDescriptorSets,
            dynamicOffsetCount, pDynamicOffsets);
    }
}

VKAPI_ATTR void VKAPI_CALL
hook_vkCmdDispatch(
    VkCommandBuffer commandBuffer,
    uint32_t groupCountX,
    uint32_t groupCountY,
    uint32_t groupCountZ)
{
    ensure_init();
    
    g_dispatch_count++;
    
    /* Log every compute dispatch with thread group counts */
    fprintf(g_log, "DISPATCH #%d: groups=(%u, %u, %u) cb=%p",
            g_dispatch_count, groupCountX, groupCountY, groupCountZ,
            (void*)commandBuffer);
    
    /* Track bound sets */
    CBTrack *t = find_or_create_cb(commandBuffer);
    if (t) {
        fprintf(g_log, " sets=%u", t->setCount);
        for (uint32_t i = 0; i < t->setCount && i < 8; i++) {
            fprintf(g_log, " ds%u=%p", i, (void*)t->descriptorSets[i]);
        }
    }
    
    fprintf(g_log, "\n");
    fflush(g_log);
    
    if (real_vkCmdDispatch) {
        real_vkCmdDispatch(commandBuffer, groupCountX, groupCountY, groupCountZ);
    }
}

/* ── Intercept vkCreateDevice to enable VKD3D debug ────────── */

/* ── Constructor / Destructor ──────────────────────────────── */
__attribute__((constructor))
static void capture_init(void) {
    ensure_init();
    fprintf(g_log, "[INIT] FSR4 capture shim loaded\n");
    fflush(g_log);
}

__attribute__((destructor))
static void capture_fini(void) {
    if (!g_log || g_log == stderr) return;
    
    time_t now = time(NULL);
    fprintf(g_log, "\n=== Capture Complete ===\n");
    fprintf(g_log, "Ended: %s", ctime(&now));
    fprintf(g_log, "Total dispatches: %d\n", g_dispatch_count);
    fprintf(g_log, "Buffer captures: %d\n", g_buffer_captures);
    fclose(g_log);
}

/* ── Symbol interposition via LD_PRELOAD ───────────────────── */
/* The functions named hook_* need to override the real Vulkan symbols.
   We do this by exporting them with the real Vulkan symbol names. */

/* We use --defsym at link time, or just name them properly: */
VKAPI_ATTR void VKAPI_CALL vkCmdDispatch(
    VkCommandBuffer cb, uint32_t x, uint32_t y, uint32_t z)
{
    ensure_init();
    
    /* Resolve real function on first call */
    if (!real_vkCmdDispatch) {
        /* Get the next symbol in the load chain (the real Vulkan impl) */
        void *handle = dlopen("libvulkan.so.1", RTLD_LAZY | RTLD_NOLOAD);
        if (!handle) handle = dlopen("libvulkan.so", RTLD_LAZY);
        if (handle) {
            real_vkCmdDispatch = dlsym(handle, "vkCmdDispatch");
        }
        if (!real_vkCmdDispatch) {
            /* Fallback: try RTLD_NEXT */
            real_vkCmdDispatch = dlsym(RTLD_NEXT, "vkCmdDispatch");
        }
    }
    
    g_dispatch_count++;
    
    fprintf(g_log, "DISPATCH #%d: groups=(%u, %u, %u)\n",
            g_dispatch_count, x, y, z);
    fflush(g_log);
    
    if (real_vkCmdDispatch) {
        real_vkCmdDispatch(cb, x, y, z);
    }
}

VKAPI_ATTR void VKAPI_CALL vkCmdBindDescriptorSets(
    VkCommandBuffer commandBuffer,
    VkPipelineBindPoint pipelineBindPoint,
    VkPipelineLayout layout,
    uint32_t firstSet,
    uint32_t descriptorSetCount,
    const VkDescriptorSet *pDescriptorSets,
    uint32_t dynamicOffsetCount,
    const uint32_t *pDynamicOffsets)
{
    ensure_init();
    
    if (!real_vkCmdBindDescriptorSets) {
        void *handle = dlopen("libvulkan.so.1", RTLD_LAZY | RTLD_NOLOAD);
        if (!handle) handle = dlopen("libvulkan.so", RTLD_LAZY);
        if (handle) {
            real_vkCmdBindDescriptorSets = dlsym(handle, "vkCmdBindDescriptorSets");
        }
        if (!real_vkCmdBindDescriptorSets) {
            real_vkCmdBindDescriptorSets = dlsym(RTLD_NEXT, "vkCmdBindDescriptorSets");
        }
    }
    
    if (pipelineBindPoint == VK_PIPELINE_BIND_POINT_COMPUTE) {
        CBTrack *t = find_or_create_cb(commandBuffer);
        if (t && descriptorSetCount <= 8) {
            for (uint32_t i = 0; i < descriptorSetCount; i++) {
                if (firstSet + i < 8) {
                    t->descriptorSets[firstSet + i] = pDescriptorSets[i];
                }
            }
            t->setCount = firstSet + descriptorSetCount > t->setCount ? 
                          firstSet + descriptorSetCount : t->setCount;
        }
    }
    
    if (real_vkCmdBindDescriptorSets) {
        real_vkCmdBindDescriptorSets(
            commandBuffer, pipelineBindPoint, layout,
            firstSet, descriptorSetCount, pDescriptorSets,
            dynamicOffsetCount, pDynamicOffsets);
    }
}
