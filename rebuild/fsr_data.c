#include <string.h>

struct blob_entry {
    const void* data;
    const unsigned int* size;
    const char* name;
};

/* All blob symbols defined in asm below */
extern const unsigned char drs_blob[];
extern const unsigned char ultraperf_blob[];
extern const unsigned char balanced_blob[];
extern const unsigned char performance_blob[];
extern const unsigned char native_blob[];
extern const unsigned char quality_blob[];
extern const unsigned int blob_size_val;

/* 
 * Everything in .data, exactly ordered via asm.
 * The compiler must NOT place any C statics in .data.
 * Only entries[] goes to .rdata (it has pointers needing relocation).
 */
__asm__(
    ".section .data\n"
    ".align 8\n"
    /* 8 bytes: value 1 (matches original offset +0x00) */
    ".quad 1\n"
    /* 24 bytes padding (to offset 0x20) */
    ".zero 24\n"
    /* 4 bytes: blob size = 0x20000 = 131072 (at offset 0x20) */
    ".long 0x20000\n"
    /* 4 bytes padding */
    ".long 0\n"
    /* 24 bytes padding (to offset 0x40) */
    ".zero 24\n"
    /* drs_blob at offset 0x40 */
    ".global drs_blob\n"
    "drs_blob:\n"
    ".incbin \"../extracted/v410_initializers/drs.bin\"\n"
    ".global ultraperf_blob\n"
    "ultraperf_blob:\n"
    ".incbin \"../extracted/v410_initializers/ultraperf.bin\"\n"
    ".global balanced_blob\n"
    "balanced_blob:\n"
    ".incbin \"../extracted/v410_initializers/balanced.bin\"\n"
    ".global performance_blob\n"
    "performance_blob:\n"
    ".incbin \"../extracted/v410_initializers/performance.bin\"\n"
    ".global native_blob\n"
    "native_blob:\n"
    ".incbin \"../extracted/v410_initializers/native.bin\"\n"
    ".global quality_blob\n"
    "quality_blob:\n"
    ".incbin \"../extracted/v410_initializers/quality.bin\"\n"
    ".text\n"
);

/* Put the size constant in .rdata, not .data, to avoid conflicting with asm layout */
__attribute__((section(".rdata")))
static const unsigned int _bsz = 0x20000;

static const struct blob_entry entries[] = {
    { quality_blob, &_bsz, "quality" },
    { balanced_blob, &_bsz, "balanced" },
    { performance_blob, &_bsz, "performance" },
    { ultraperf_blob, &_bsz, "ultraperf" },
    { native_blob, &_bsz, "native" },
    { drs_blob, &_bsz, "drs" },
};

int fsr_data_version(void) { return 0x40100; }
int fsr_data_blob_count(void) { return 6; }
int fsr_data_blob_size(int idx) { (void)idx; return 0x20000; }
const struct blob_entry* fsr_data_get_blob(unsigned long long idx) {
    if (idx > 5) return (const void*)0;
    return &entries[idx];
}
const struct blob_entry* fsr_data_find_blob(const char* name) {
    int i;
    if (!name) return (const struct blob_entry*)0;
    for (i = 0; i < 6; i++) {
        if (strcmp(entries[i].name, name) == 0) return &entries[i];
    }
    return (const struct blob_entry*)0;
}
