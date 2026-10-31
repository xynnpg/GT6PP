/*
 * GT6-specific HLE overrides.
 *
 * ps3recomp's cellSpurs implements the workload scheduler but not every
 * workload-flag accessor GT6 imports. `cellSpursGetWorkloadFlag` is called by
 * the engine's workload bootstrap: it passes a SPURS instance and a pointer to
 * receive the flag address. The real flag is the 64-bit wklFlag at
 * CellSpurs+0x60 (see libs/spurs/cellSpurs.c, SPURS_WKL_FLAG). Returning
 * without writing it left the caller with a null/garbage flag and the engine's
 * boot path aborted.
 *
 * Three more imports were unresolved at boot. Their names are confirmed by the
 * real GT6 RPCS3 boot log (the firmware libsre/libusbd export tables print the
 * exact NID -> name mapping) and independently by SHA-1 NID recomputation with
 * the PS3 NID suffix:
 *
 *   0x2DDBCC0A  cellSpurs  _cellSpursWorkloadFlagReceiver2(spurs, wid,
 *                                                        is_set, debug)
 *   0xFAA275A4  cellSysutilAvconfExt  cellVideoOutGetScreenSize(videoOut,
 *                                                               float*)
 *   0x5C832BD7  cellUsbd   cellUsbdSetThreadPriority2(prio0, prio1, prio2)
 *
 * CellSpurs layout (big-endian guest memory; RPCS3 cellSpurs.h and
 * ps3recomp libs/spurs/cellSpurs.c agree):
 *   +0x60  CellSpursWorkloadFlag (16 bytes)
 *   +0x6C    u32 flag word (0xFFFFFFFF = not signalled)
 *   +0x77    u8  wklFlagReceiver (0xFF = no receiver)
 * ps3recomp does not initialise the receiver byte, so a zero there is treated
 * as "no receiver" for a fresh instance (the firmware writes 0xFF at init).
 * Once a receiver is set, the flag word distinguishes wid 0 from "free".
 *
 * These overrides run after ppu_hle_register_all(), so they replace the
 * unresolved-import fallback for the same NID. The runtime checks the
 * ps3_hle_register_ctx table before the generic NID table, so registering a
 * NID here also wins over any generic ps3recomp handler.
 */
#include "ppu_context.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

extern "C" {
void     vm_write8(uint64_t addr, uint8_t val);
void     vm_write32(uint64_t addr, uint32_t val);
void     vm_write64(uint64_t addr, uint64_t val);
uint8_t  vm_read8(uint64_t addr);
uint32_t vm_read32(uint64_t addr);
}

/* -------------------------------------------------------------------------
 * Boot-script stream override.
 *
 * The guest's PFS cache layer currently returns 0 bytes for
 * `scripts/gt6/main.adc`: the PD.fdupi cache has a compressed ZSize but an
 * empty block map, and the copy thread fills it only after the script loader
 * has already read the header. The container bytes are correct and the title's
 * own cipher seed (FileIndex 33) decrypts the entry to the 857,518-byte
 * `ADCH012\0` file in work/gt6_vol.
 *
 * Until the PFS read-through decrypt is wired for every file, serve this one
 * boot script from the already-decrypted host file. The override is installed
 * when HFileReader::open sees the script path, and HFileReader::read consumes
 * the same stream sequentially, so the 8-byte ADCH check, the version read and
 * the parser all see one consistent file. No other file is affected.
 *
 * The hook is restricted to the HFileReader that opened the script. The real
 * HFileReader keeps a 0x1000-byte read-ahead buffer described by +0x1A8
 * (buffer), +0x1AC (buffer length) and +0x1B0 (buffer position); the override
 * serves no look-ahead, so it keeps those fields at zero and only advances the
 * guest-visible file offset at +0x1B4 (HFileReader::tell returns that word).
 * Set GT6_SCRIPT_TRACE=1 to log every read/seek for parser triage.
 * ---------------------------------------------------------------------- */
static unsigned char* g_script_data;
static size_t         g_script_size;
static size_t         g_script_pos;
static int            g_script_active;
static uint32_t       g_script_reader;   /* HFileReader this pointer */

static int gt6_script_trace(void)
{
    static int on = -1;
    if (on < 0) {
        const char* e = getenv("GT6_SCRIPT_TRACE");
        on = (e && *e && *e != '0') ? 1 : 0;
    }
    return on;
}

/* The path seen at HFileReader::open is "/scripts/gt6/main.adc"; match the
 * suffix exactly so unrelated files are never replaced. */
static int gt6_script_path_matches(const char* path)
{
    static const char suffix[] = "scripts/gt6/main.adc";
    size_t plen = strlen(path);
    size_t slen = sizeof suffix - 1;
    return plen >= slen && strcmp(path + plen - slen, suffix) == 0;
}

extern "C" int gt6_script_override_active(void)
{
    return g_script_active;
}

static void gt6_script_unload(void)
{
    free(g_script_data);
    g_script_data = NULL;
    g_script_size = 0;
    g_script_pos = 0;
    g_script_active = 0;
    g_script_reader = 0;
}

/* -------------------------------------------------------------------------
 * Generic PFS plaintext override (K/WO and every extracted PFS file).
 *
 * The PDIPFS cache files (.fdupi/.fdupm) hold the *raw* GT.VOL stream, not
 * plaintext: sound_gt/se/gt6sys.sgd (K/IK, uncompressed) is byte-identical in
 * work/gt6_vol and in PDIPFS/K/IK, and GTToolsSharp decrypts that same slice
 * with seed 31 to reproduce the extracted file.  The guest is supposed to
 * decrypt the cached stream with the PFS cipher at 0x9FF530 and then inflate
 * compressed entries with PDISTD::SpuInflator (vtable 0x148A2D0, inflate
 * 0xA43AB4).  While that path is incomplete, serve the already-decrypted
 * extracted file from work/gt6_vol through the HFileReader hooks that already
 * exist for the boot script.
 *
 * The override only activates when the host file exists.  Any file that has
 * not been extracted keeps the guest path, so this cannot make a missing
 * asset look present.
 *
 * Key mapping: the GT.VOL TOC names a cache object by its FileIndex string
 * (e.g. K/WO -> products/gt6/script/MenuClassDefine.adc).  The normal
 * HFileReader path is already the virtual path, so a map is only needed when
 * a caller opens the cache key itself (PDIPFS/K/WO or K/WO).  Those keys are
 * resolved through work/gt6_pfs_keymap.tsv, generated by
 * tools/patches/gt6_pfs_make_keymap.py from the GTToolsSharp TOC listing.
 *
 * Environment:
 *   GT6_PFS_OVERRIDE=0     disable this override
 *   GT6_PFS_TRACE=1        log every open/read/seek
 *   GT6_PFS_MAX_MB=<n>     per-file cap in MiB (default 64)
 *   GT6_VOL_ROOT=<dir>     extracted tree (default work/gt6_vol)
 *   GT6_PFS_KEYMAP=<file>  key map (default work/gt6_pfs_keymap.tsv)
 * ---------------------------------------------------------------------- */
extern "C" uint8_t* vm_base;

enum {
    /* Eight PFS streams were enough before; the font preload opens about
     * a dozen host FileObjects (menu_imagefont.bin plus the .vec faces),
     * so keep headroom for both key spaces. */
    GT6_PFS_SLOTS      = 16,
    GT6_PFS_PATH_MAX   = 256,
    GT6_PFS_HOST_MAX   = 512,
    GT6_PFS_DEFAULT_MB = 64
};

struct Gt6PfsSlot {
    uint32_t       reader;   /* HFileReader key (0x9BB020), 0 for host */
    uint32_t       file;     /* FileObject key (0x9F8E40), 0 for reader */
    uint32_t       size;
    uint32_t       pos;
    uint64_t       stamp;
    unsigned char* data;
    char           path[GT6_PFS_PATH_MAX];
};

static Gt6PfsSlot g_pfs_slots[GT6_PFS_SLOTS];
static uint64_t   g_pfs_stamp;

static int gt6_pfs_trace(void)
{
    static int on = -1;
    if (on < 0) {
        const char* e = getenv("GT6_PFS_TRACE");
        on = (e && *e && *e != '0') ? 1 : 0;
    }
    return on;
}

static int gt6_pfs_disabled(void)
{
    const char* e = getenv("GT6_PFS_OVERRIDE");
    return e && *e == '0';
}

static size_t gt6_pfs_max_bytes(void)
{
    static size_t cap;
    if (!cap) {
        const char* e = getenv("GT6_PFS_MAX_MB");
        long mb = (e && *e) ? strtol(e, NULL, 0) : GT6_PFS_DEFAULT_MB;
        if (mb < 1) mb = 1;
        if (mb > 1024) mb = 1024;
        cap = (size_t)mb * 1024u * 1024u;
    }
    return cap;
}

/* Locate the extracted tree.  The test runner's working directory is the
 * repository root (the boot-script override already relies on that), but
 * accept the build-directory variants as well. */
static const char* gt6_pfs_root(void)
{
    static char root[GT6_PFS_HOST_MAX];
    static int  initialized;
    if (initialized) return root[0] ? root : NULL;
    initialized = 1;

    const char* candidates[] = {
        getenv("GT6_VOL_ROOT"),
        "work/gt6_vol",
        "../work/gt6_vol",
        "../../work/gt6_vol",
    };
    for (size_t i = 0; i < sizeof candidates / sizeof candidates[0]; i++) {
        const char* c = candidates[i];
        if (!c || !*c) continue;
        snprintf(root, sizeof root, "%s", c);
        char probe[GT6_PFS_HOST_MAX];
        snprintf(probe, sizeof probe, "%s/VER_INFO", root);
        FILE* f = fopen(probe, "rb");
        if (f) { fclose(f); return root; }
    }
    root[0] = 0;
    return NULL;
}

static const char* gt6_pfs_keymap(void)
{
    static char path[GT6_PFS_HOST_MAX];
    static int  initialized;
    if (initialized) return path[0] ? path : NULL;
    initialized = 1;

    const char* candidates[] = {
        getenv("GT6_PFS_KEYMAP"),
        "work/gt6_pfs_keymap.tsv",
        "../work/gt6_pfs_keymap.tsv",
        "../../work/gt6_pfs_keymap.tsv",
    };
    for (size_t i = 0; i < sizeof candidates / sizeof candidates[0]; i++) {
        const char* c = candidates[i];
        if (!c || !*c) continue;
        FILE* f = fopen(c, "rb");
        if (f) {
            fclose(f);
            snprintf(path, sizeof path, "%s", c);
            return path;
        }
    }
    path[0] = 0;
    return NULL;
}

/* Normalize a guest virtual path into a relative POSIX-style path.  Reject
 * anything that could escape the extracted root. */
static int gt6_pfs_relpath(const char* in, char* out, size_t cap)
{
    if (!in || !*in) return 0;
    size_t j = 0;
    for (size_t i = 0; in[i]; i++) {
        char c = in[i];
        if (c == '\\') c = '/';
        if (c == '/') {
            if (j == 0) continue;              /* strip leading '/' */
            if (out[j - 1] == '/') continue;   /* collapse // */
        }
        if ((unsigned char)c < 0x20) return 0;
        if (j + 1 >= cap) return 0;
        out[j++] = c;
    }
    out[j] = 0;
    if (j == 0 || out[0] == '/') return 0;
    if (strstr(out, "..")) return 0;           /* conservative: no '..' */
    if (strchr(out, ':')) return 0;
    return 1;
}

static const char* gt6_pfs_strip_cache_prefix(const char* s)
{
    static const char* prefixes[] = {
        "PDIPFS_bdmark/", "PDIPFS/", "pdipfs/",
    };
    for (size_t i = 0; i < sizeof prefixes / sizeof prefixes[0]; i++) {
        size_t n = strlen(prefixes[i]);
        if (strncmp(s, prefixes[i], n) == 0) return s + n;
    }
    /* Also accept a full device path that embeds the cache directory. */
    for (size_t i = 0; i < sizeof prefixes / sizeof prefixes[0]; i++) {
        const char* p = strstr(s, prefixes[i]);
        if (p) return p + strlen(prefixes[i]);
    }
    return s;
}

/* Cache keys look like K/WO or 5T/AM: one or two symbols, a slash, then two
 * symbols.  Normal virtual paths have longer components. */
static int gt6_pfs_key_shape(const char* s)
{
    const char* slash = strchr(s, '/');
    if (!slash || slash == s) return 0;
    size_t a = (size_t)(slash - s);
    size_t b = strlen(slash + 1);
    if (a > 2 || b != 2) return 0;
    for (const char* p = s; *p; p++) {
        if (*p == '/') continue;
        if (!((*p >= '0' && *p <= '9') || (*p >= 'A' && *p <= 'Z')))
            return 0;
    }
    return 1;
}

/* key<TAB>virtual_path<TAB>... */
static int gt6_pfs_lookup_key(const char* key, char* out, size_t cap)
{
    const char* map = gt6_pfs_keymap();
    if (!map) return 0;
    FILE* f = fopen(map, "rb");
    if (!f) return 0;

    char line[1024];
    int found = 0;
    int matches = 0;
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') continue;
        char* nl = strchr(line, '\n'); if (nl) *nl = 0;
        char* cr = strchr(line, '\r'); if (cr) *cr = 0;
        char* tab = strchr(line, '\t');
        if (!tab) continue;
        *tab = 0;
        if (strcmp(line, key) != 0) continue;
        char* path = tab + 1;
        char* tab2 = strchr(path, '\t');
        if (tab2) *tab2 = 0;
        if (!found && *path) {
            snprintf(out, cap, "%s", path);
            found = 1;
        }
        matches++;
    }
    fclose(f);

    if (matches > 1 && gt6_pfs_trace())
        fprintf(stderr, "[GT6] pfs override: key %s has %d TOC matches; using the first\n",
                key, matches);
    return found;
}

/* Trace the TOC row for a virtual path (GT6_PFS_TRACE only).  This is what
 * turns "the override served something" into "it served the K/WO entry". */
static void gt6_pfs_trace_toc(const char* rel)
{
    if (!gt6_pfs_trace()) return;
    const char* map = gt6_pfs_keymap();
    if (!map) return;
    FILE* f = fopen(map, "rb");
    if (!f) return;

    char line[1024];
    while (fgets(line, sizeof line, f)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r') continue;
        char* nl = strchr(line, '\n'); if (nl) *nl = 0;
        char* cr = strchr(line, '\r'); if (cr) *cr = 0;
        char* f1 = strchr(line, '\t'); if (!f1) continue;
        *f1++ = 0;
        char* f2 = strchr(f1, '\t'); if (!f2) continue;
        *f2++ = 0;
        if (strcmp(f1, rel) != 0) continue;
        /* key, path, flags, file_index, seg_index, zsize, size, offset */
        char* f3 = strchr(f2, '\t'); if (f3) *f3++ = 0;
        char* f4 = f3 ? strchr(f3, '\t') : NULL; if (f4) *f4++ = 0;
        char* f5 = f4 ? strchr(f4, '\t') : NULL; if (f5) *f5++ = 0;
        char* f6 = f5 ? strchr(f5, '\t') : NULL; if (f6) *f6++ = 0;
        char* f7 = f6 ? strchr(f6, '\t') : NULL; if (f7) *f7++ = 0;
        char* f8 = f7 ? strchr(f7, '\t') : NULL; if (f8) *f8 = 0;
        fprintf(stderr, "[pfstoc] key=%s path=%s flags=%s file=%s seg=%s "
                        "zsize=%s size=%s offset=%s\n",
                line, f1, f2, f3 ? f3 : "?", f4 ? f4 : "?",
                f5 ? f5 : "?", f6 ? f6 : "?", f7 ? f7 : "?");
        break;
    }
    fclose(f);
}

/* Resolve virtual path -> host file.  First try the path directly, then (for
 * cache-key opens) translate the key through the TOC map. */
static int gt6_pfs_resolve(const char* rel, char* host, size_t cap,
                           char* resolved_rel, size_t resolved_cap)
{
    const char* root = gt6_pfs_root();
    if (!root) return 0;

    snprintf(host, cap, "%s/%s", root, rel);
    FILE* f = fopen(host, "rb");
    if (f) {
        fclose(f);
        snprintf(resolved_rel, resolved_cap, "%s", rel);
        return 1;
    }

    const char* key = gt6_pfs_strip_cache_prefix(rel);
    if (!gt6_pfs_key_shape(key)) return 0;

    char vpath[GT6_PFS_PATH_MAX];
    if (!gt6_pfs_lookup_key(key, vpath, sizeof vpath)) return 0;

    snprintf(host, cap, "%s/%s", root, vpath);
    f = fopen(host, "rb");
    if (!f) {
        if (gt6_pfs_trace())
            fprintf(stderr, "[GT6] pfs override: key %s -> %s, but no extracted file\n",
                    key, vpath);
        return 0;
    }
    fclose(f);
    snprintf(resolved_rel, resolved_cap, "%s", vpath);
    return 1;
}

static void gt6_pfs_slot_clear(Gt6PfsSlot* s)
{
    if (!s) return;
    if (s->data) free(s->data);
    memset(s, 0, sizeof *s);
}

static Gt6PfsSlot* gt6_pfs_find(uint32_t reader)
{
    for (int i = 0; i < GT6_PFS_SLOTS; i++)
        if (g_pfs_slots[i].data && g_pfs_slots[i].reader == reader)
            return &g_pfs_slots[i];
    return NULL;
}

/* Host opens are keyed by the FileObject pointer (r4 at 0x9F8E40, also
 * the success return value).  The read helpers find it at
 * FileStream+0x44; HFileReader::read (0x9BB020) uses reader+0x74, which
 * is the same word because its FileStream lives at reader+0x30. */
static Gt6PfsSlot* gt6_pfs_find_file(uint32_t file)
{
    if (!file) return NULL;
    for (int i = 0; i < GT6_PFS_SLOTS; i++)
        if (g_pfs_slots[i].data && g_pfs_slots[i].file == file)
            return &g_pfs_slots[i];
    return NULL;
}

static Gt6PfsSlot* gt6_pfs_slot_for(uint32_t reader, uint32_t file)
{
    Gt6PfsSlot* s = reader ? gt6_pfs_find(reader) : gt6_pfs_find_file(file);
    if (s) return s;

    for (int i = 0; i < GT6_PFS_SLOTS; i++)
        if (!g_pfs_slots[i].data) return &g_pfs_slots[i];

    /* Evict the least recently used stream. */
    Gt6PfsSlot* lru = &g_pfs_slots[0];
    for (int i = 1; i < GT6_PFS_SLOTS; i++)
        if (g_pfs_slots[i].stamp < lru->stamp) lru = &g_pfs_slots[i];
    gt6_pfs_slot_clear(lru);
    return lru;
}

/* Read one extracted file into a slot.  The caller has already cleared
 * any stale stream for the key.  Shared by the HFileReader path hint and
 * the 0x9F8E40 host-open key so both obey the same path/TOC rules. */
static int gt6_pfs_install(const char* rel, uint32_t reader, uint32_t file)
{
    char host[GT6_PFS_HOST_MAX];
    char resolved[GT6_PFS_PATH_MAX];
    if (!gt6_pfs_resolve(rel, host, sizeof host, resolved, sizeof resolved)) {
        if (gt6_pfs_trace())
            fprintf(stderr, "[GT6] pfs override: no extracted file for '%s'\n", rel);
        return 0;
    }

    FILE* f = fopen(host, "rb");
    if (!f) return 0;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return 0; }
    long n = ftell(f);
    if (n <= 0 || (uint64_t)n > (uint64_t)gt6_pfs_max_bytes()) {
        fclose(f);
        if (gt6_pfs_trace())
            fprintf(stderr, "[GT6] pfs override: skipping '%s' (%ld bytes, cap %zu)\n",
                    resolved, n, gt6_pfs_max_bytes());
        return 0;
    }
    if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); return 0; }

    unsigned char* buf = (unsigned char*)malloc((size_t)n);
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        free(buf);
        fclose(f);
        return 0;
    }
    fclose(f);

    Gt6PfsSlot* s = gt6_pfs_slot_for(reader, file);
    s->reader = reader;
    s->file   = file;
    s->size   = (uint32_t)n;
    s->pos    = 0;
    s->stamp  = ++g_pfs_stamp;
    s->data   = buf;
    snprintf(s->path, sizeof s->path, "%s", resolved);

    if (gt6_pfs_trace()) gt6_pfs_trace_toc(resolved);

    if (reader)
        fprintf(stderr, "[GT6] pfs override: serving plaintext %s (%ld bytes, reader=0x%08X)\n",
                resolved, n, (unsigned)reader);
    else
        fprintf(stderr, "[GT6] pfs override: serving plaintext %s (%ld bytes, file=0x%08X, host open)\n",
                resolved, n, (unsigned)file);
    return 1;
}

static void gt6_pfs_unload_reader(uint32_t reader)
{
    Gt6PfsSlot* s = gt6_pfs_find(reader);
    if (s) gt6_pfs_slot_clear(s);
}

/* Called from HFileReader::open before the guest mount lookup. */
static void gt6_pfs_path_hint(uint32_t reader_ea, const char* path)
{
    if (gt6_pfs_disabled()) return;

    /* A new open on this reader replaces whatever stream the previous open
     * installed.  Clearing first also handles "open a file we cannot serve":
     * stale bytes must never be returned for the new file. */
    Gt6PfsSlot* old = gt6_pfs_find(reader_ea);
    if (old) gt6_pfs_slot_clear(old);

    char rel[GT6_PFS_PATH_MAX];
    if (!path || !gt6_pfs_relpath(path, rel, sizeof rel)) return;

    if (gt6_pfs_trace())
        fprintf(stderr, "[pfshint] reader=0x%08X path='%s'\n",
                (unsigned)reader_ea, rel);

    /* The boot-script override owns scripts/gt6/main.adc. */
    if (gt6_script_path_matches(rel)) return;

    gt6_pfs_install(rel, reader_ea, 0);
}

/* Called at the top of HFileReader::read (0x9BB020). */
static int gt6_pfs_read_override(ppu_context* ctx)
{
    if (gt6_pfs_disabled()) return 0;
    const uint32_t reader = (uint32_t)ctx->gpr[3];
    Gt6PfsSlot* s = gt6_pfs_find(reader);
    if (!s) {
        /* HFileReader keeps its FileStream at reader+0x30, and the
         * FileObject pointer at FileStream+0x44 (= reader+0x74). */
        const uint32_t file = reader ? vm_read32((uint64_t)reader + 0x74u) : 0;
        s = gt6_pfs_find_file(file);
    }
    if (!s || !s->data) return 0;

    uint32_t out = (uint32_t)ctx->gpr[4];
    uint32_t n   = (uint32_t)ctx->gpr[5];
    s->stamp = ++g_pfs_stamp;

    if (gt6_pfs_trace())
        fprintf(stderr, "[pfsov] this=0x%08X file=0x%08X n=%u pos=%u/%u %s\n",
                (unsigned)reader, (unsigned)s->file, (unsigned)n,
                s->pos, s->size, s->path);

    if (n == 0) { ctx->gpr[3] = 0; return 1; }
    if (out == 0) return 0;   /* never write through a null guest buffer */
    if (s->pos >= s->size) {
        vm_write32((uint64_t)reader + 0x18, 1);   /* HFileReader EOF state */
        ctx->gpr[3] = 0;
        return 1;
    }

    uint32_t k = n;
    if (k > s->size - s->pos) k = s->size - s->pos;

    if (vm_base) {
        memcpy(vm_base + out, s->data + s->pos, k);
    } else {
        for (uint32_t i = 0; i < k; i++)
            vm_write8((uint64_t)out + i, s->data[s->pos + i]);
    }
    s->pos += k;

    /* Keep HFileReader's guest-visible offset and empty read-ahead buffer
     * coherent (same fields the boot-script override maintains). */
    vm_write32((uint64_t)reader + 0x1B4, s->pos);
    vm_write32((uint64_t)reader + 0x1AC, 0);
    vm_write32((uint64_t)reader + 0x1B0, 0);
    if (s->pos >= s->size)
        vm_write32((uint64_t)reader + 0x18, 1);   /* HFileReader EOF state */

    ctx->gpr[3] = k;
    return 1;
}

/* Called at the top of HFileReader::seek (0x9BAFE0). */
static int gt6_pfs_seek_override(ppu_context* ctx)
{
    if (gt6_pfs_disabled()) return 0;
    const uint32_t reader = (uint32_t)ctx->gpr[3];
    Gt6PfsSlot* s = gt6_pfs_find(reader);
    if (!s) {
        const uint32_t file = reader ? vm_read32((uint64_t)reader + 0x74u) : 0;
        s = gt6_pfs_find_file(file);
    }
    if (!s || !s->data) return 0;

    int32_t off = (int32_t)ctx->gpr[4];
    if (off < 0) off = 0;
    s->pos = (uint32_t)off;
    s->stamp = ++g_pfs_stamp;

    vm_write32((uint64_t)reader + 0x1B4, s->pos);
    vm_write32((uint64_t)reader + 0x1AC, 0);
    vm_write32((uint64_t)reader + 0x1B0, 0);

    if (gt6_pfs_trace())
        fprintf(stderr, "[pfsseek] this=0x%08X file=0x%08X -> %u/%u\n",
                (unsigned)reader, (unsigned)s->file, s->pos, s->size);

    ctx->gpr[3] = 0;
    return 1;
}

/* Read a guest C string. Rejects nothing here; the caller decides whether the
 * bytes look like a path. */
static int gt6_read_guest_cstr(uint32_t ea, char* out, size_t cap)
{
    if (!ea) return 0;
    for (size_t i = 0; i + 1 < cap; i++) {
        char c = (char)vm_read8((uint64_t)ea + i);
        out[i] = c;
        if (!c) return i > 0;
    }
    out[cap - 1] = 0;
    return 1;
}

/* A virtual path is printable ASCII and contains a '/'. This distinguishes a
 * real C++ string object's character buffer from a raw "K/W2" word read as if
 * it were a pointer. */
static int gt6_path_looks_valid(const char* s)
{
    if (!s || !*s) return 0;
    int slash = 0;
    for (const char* p = s; *p; p++) {
        unsigned char c = (unsigned char)*p;
        if (c < 0x20 || c > 0x7E) return 0;
        if (c == '/') slash = 1;
    }
    return slash;
}


/* -------------------------------------------------------------------------
 * Host FileObject override (the /font/... path).
 *
 * 0x9F8E40 is `open(path, FileObject*, mode)`: r3 is the guest path string,
 * r4 is the FileObject the device fills in, and the success return is r4.
 * The boot UI reaches it through 0x9F79A8 -> 0x9F73E8 -> 0x9F719C ->
 * 0x9F6BF4; HFileReader reaches it through 0x9F4130 -> 0x9F6BF4.
 *
 * Device reads go through the FileStream helpers, not HFileReader::read:
 *   0x9F4AA0(stream, req)  req = { u32 buf; u32 len; }
 *   0x9F49D8(stream, origin, offset)
 *   0x9F4930(stream) -> position
 * and every one of them resolves the FileObject at [stream+0x44].  The host
 * device services 0x9F4AA0 asynchronously (0xA08ED0 submits to the worker at
 * 0xA09288 and waits at 0xA21D50), which is where the menu font preload
 * stalls.  The slot installed below is keyed by the FileObject pointer and
 * served synchronously from work/gt6_vol.  It is independent of the PFS
 * key/TOC slots (keyed by the HFileReader) and of the boot-script override.
 * ---------------------------------------------------------------------- */
extern "C" void gt6_pfs_host_open_prepare(uint32_t path_ea, uint32_t file_ea)
{
    if (gt6_pfs_disabled() || !file_ea) return;

    /* A re-used FileObject must never inherit the previous file's bytes. */
    Gt6PfsSlot* old = gt6_pfs_find_file(file_ea);
    if (old) gt6_pfs_slot_clear(old);

    char path[GT6_PFS_PATH_MAX];
    if (!gt6_read_guest_cstr(path_ea, path, sizeof path)) return;

    char rel[GT6_PFS_PATH_MAX];
    if (!gt6_pfs_relpath(path, rel, sizeof rel)) return;

    /* The boot-script override owns scripts/gt6/main.adc. */
    if (gt6_script_path_matches(rel)) return;

    if (gt6_pfs_trace())
        fprintf(stderr, "[hostopen] file=0x%08X path='%s'\n",
                (unsigned)file_ea, rel);

    gt6_pfs_install(rel, 0, file_ea);
}

/* Called by the wrapper after 0x9F8E40 returns.  The measured device opens
 * return the same FileObject that was passed in r4; re-key defensively if a
 * device ever allocates/returns a different pointer, and drop the slot when
 * the open failed. */
extern "C" void gt6_pfs_host_open_commit(uint32_t file_ea, uint32_t ret_ea)
{
    Gt6PfsSlot* s = gt6_pfs_find_file(file_ea);
    if (!s) return;

    uint32_t file = file_ea;
    if (ret_ea != file_ea) {
        if (ret_ea < 0x00010000u || ret_ea >= 0xFFFFFFF0u) {
            gt6_pfs_slot_clear(s);
            return;
        }
        s->file = ret_ea;
        file = ret_ea;
    }

    /* The device open runs inside 0x9F8E40 and may leave FileObject+0xC0 at
     * zero for a host file.  HFileReader::read uses that word as the size. */
    vm_write64((uint64_t)file + 0xC0u, (uint64_t)s->size);
}

/* Called at the top of 0x9F4AA0.  r4 points at the {buf,len} request the
 * device read would consume. */
extern "C" int gt6_pfs_stream_read_override(ppu_context* ctx)
{
    if (gt6_pfs_disabled()) return 0;
    const uint32_t stream = (uint32_t)ctx->gpr[3];
    const uint32_t req    = (uint32_t)ctx->gpr[4];
    if (!stream || !req) return 0;

    const uint32_t file = vm_read32((uint64_t)stream + 0x44u);
    Gt6PfsSlot* s = gt6_pfs_find_file(file);
    if (!s || !s->data) return 0;

    const uint32_t out = vm_read32((uint64_t)req + 0u);
    uint32_t n         = vm_read32((uint64_t)req + 4u);
    s->stamp = ++g_pfs_stamp;

    if (gt6_pfs_trace())
        fprintf(stderr, "[hostov] stream=0x%08X file=0x%08X n=%u pos=%u/%u %s\n",
                (unsigned)stream, (unsigned)file, (unsigned)n,
                s->pos, s->size, s->path);

    if (out == 0) return 0;   /* never write through a null guest buffer */
    if (n == 0 || s->pos >= s->size) {
        ctx->gpr[3] = 0;
        return 1;
    }

    uint32_t k = n;
    if (k > s->size - s->pos) k = s->size - s->pos;
    if (vm_base) {
        memcpy(vm_base + out, s->data + s->pos, k);
    } else {
        for (uint32_t i = 0; i < k; i++)
            vm_write8((uint64_t)out + i, s->data[s->pos + i]);
    }
    s->pos += k;
    ctx->gpr[3] = k;
    return 1;
}

/* Called at the top of 0x9F49D8(stream, origin, offset). */
extern "C" int gt6_pfs_stream_seek_override(ppu_context* ctx)
{
    if (gt6_pfs_disabled()) return 0;
    const uint32_t stream = (uint32_t)ctx->gpr[3];
    if (!stream) return 0;

    Gt6PfsSlot* s = gt6_pfs_find_file(vm_read32((uint64_t)stream + 0x44u));
    if (!s || !s->data) return 0;

    const int32_t origin = (int32_t)ctx->gpr[4];
    const int32_t off    = (int32_t)ctx->gpr[5];
    int64_t base = 0;
    if (origin == 1) base = (int64_t)s->pos;
    else if (origin == 2) base = (int64_t)s->size;
    int64_t target = base + off;
    if (target < 0) target = 0;
    if (target > (int64_t)s->size) target = (int64_t)s->size;
    s->pos = (uint32_t)target;
    s->stamp = ++g_pfs_stamp;

    if (gt6_pfs_trace())
        fprintf(stderr, "[hostseek] stream=0x%08X origin=%d off=%d -> %u/%u\n",
                (unsigned)stream, (int)origin, (int)off, s->pos, s->size);

    ctx->gpr[3] = 0;
    return 1;
}

/* Called at the top of 0x9F4930(stream) -> position. */
extern "C" int gt6_pfs_stream_tell_override(ppu_context* ctx)
{
    if (gt6_pfs_disabled()) return 0;
    const uint32_t stream = (uint32_t)ctx->gpr[3];
    if (!stream) return 0;

    Gt6PfsSlot* s = gt6_pfs_find_file(vm_read32((uint64_t)stream + 0x44u));
    if (!s || !s->data) return 0;
    s->stamp = ++g_pfs_stamp;

    if (gt6_pfs_trace())
        fprintf(stderr, "[hosttell] stream=0x%08X -> %u/%u\n",
                (unsigned)stream, s->pos, s->size);

    ctx->gpr[3] = s->pos;
    return 1;
}

extern "C" void gt6_script_path_hint(uint32_t reader_ea, uint32_t str_ea)
{
    if (!str_ea) return;

    char path[256];
    path[0] = 0;

    /* Normal ADHOC call: r4 points at a C++ string object whose first word is
     * the character data. Some binary loaders pass the character buffer
     * directly, so fall back to str_ea itself when the first word does not
     * produce a path. */
    uint32_t data_ea = vm_read32(str_ea);
    if (data_ea) {
        char candidate[256];
        if (gt6_read_guest_cstr(data_ea, candidate, sizeof candidate) &&
            gt6_path_looks_valid(candidate)) {
            snprintf(path, sizeof path, "%s", candidate);
        }
    }
    if (!path[0]) {
        char candidate[256];
        if (gt6_read_guest_cstr(str_ea, candidate, sizeof candidate) &&
            gt6_path_looks_valid(candidate))
            snprintf(path, sizeof path, "%s", candidate);
    }
    if (!path[0]) return;

    if (gt6_pfs_trace())
        fprintf(stderr, "[pfs-open] reader=0x%08X arg=0x%08X data=0x%08X path='%s'\n",
                (unsigned)reader_ea, (unsigned)str_ea, (unsigned)data_ea, path);

    /* Generic extracted-file override.  It clears any stream previously
     * installed for this reader and ignores scripts/gt6/main.adc, which the
     * boot-script override below owns. */
    if (gt6_script_path_matches(path))
        gt6_pfs_unload_reader(reader_ea);
    else
        gt6_pfs_path_hint(reader_ea, path);

    if (!gt6_script_path_matches(path)) {
        /* A different file is being opened on the overridden reader. Stop
         * serving the boot script so the guest path handles that file. */
        if (g_script_active && reader_ea == g_script_reader)
            gt6_script_unload();
        return;
    }

    if (g_script_active && reader_ea == g_script_reader)
        return;   /* already serving this reader */

    FILE* f = fopen("work/gt6_vol/scripts/gt6/main.adc", "rb");
    if (!f) {
        fprintf(stderr, "[GT6] script override: cannot open decrypted main.adc\n");
        return;
    }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0 || (unsigned long)n > 16u * 1024u * 1024u) {
        fclose(f);
        return;
    }
    unsigned char* buf = (unsigned char*)malloc((size_t)n);
    if (!buf || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        free(buf);
        fclose(f);
        return;
    }
    fclose(f);

    gt6_script_unload();
    g_script_data = buf;
    g_script_size = (size_t)n;
    g_script_pos = 0;
    g_script_reader = reader_ea;
    g_script_active = 1;
    fprintf(stderr, "[GT6] script override: serving decrypted %s (%ld bytes)\n",
            path, n);
}

extern "C" int gt6_script_seek_override(ppu_context* ctx)
{
    if (!g_script_active || (uint32_t)ctx->gpr[3] != g_script_reader)
        return gt6_pfs_seek_override(ctx);
    /* The ADCH loader only seeks absolutely; origin (r5) is not used. */
    uint32_t off = (uint32_t)ctx->gpr[4];
    if (off > g_script_size) off = (uint32_t)g_script_size;
    g_script_pos = off;
    vm_write32((uint64_t)g_script_reader + 0x1B4, off);
    /* The override owns the stream, so the real 0x1000-byte buffer is empty. */
    vm_write32((uint64_t)g_script_reader + 0x1AC, 0);
    vm_write32((uint64_t)g_script_reader + 0x1B0, 0);
    ctx->gpr[3] = 0;
    if (gt6_script_trace())
        fprintf(stderr, "[scriptseek] -> %u/%zu\n", off, g_script_size);
    return 1;
}

extern "C" int gt6_script_read_override(ppu_context* ctx)
{
    if (!g_script_active || (uint32_t)ctx->gpr[3] != g_script_reader)
        return gt6_pfs_read_override(ctx);

    uint32_t out = (uint32_t)ctx->gpr[4];
    uint32_t n   = (uint32_t)ctx->gpr[5];

    if (gt6_script_trace())
        fprintf(stderr, "[scriptov] this=0x%08X n=%u pos=%zu/%zu\n",
                (unsigned)ctx->gpr[3], (unsigned)n,
                g_script_pos, g_script_size);

    if (n == 0) {
        ctx->gpr[3] = 0;
        return 1;
    }
    if (g_script_pos >= g_script_size) {
        ctx->gpr[3] = 0;
        return 1;
    }
    size_t k = n;
    if (k > g_script_size - g_script_pos) k = g_script_size - g_script_pos;
    for (size_t i = 0; i < k; i++)
        vm_write8((uint64_t)out + i, g_script_data[g_script_pos + i]);
    g_script_pos += k;
    /* The real HFileReader::read updates the guest-visible file offset at
     * +0x1B4. Keep it in sync; the ADCH parser uses tell() while it walks the
     * symbol table and code frame. */
    vm_write32((uint64_t)g_script_reader + 0x1B4, (uint32_t)g_script_pos);
    vm_write32((uint64_t)g_script_reader + 0x1AC, 0);
    vm_write32((uint64_t)g_script_reader + 0x1B0, 0);
    ctx->gpr[3] = k;
    return 1;
}

extern "C" void ps3_hle_register_ctx(unsigned int nid, const char* name,
                                     void (*fn)(ppu_context*));

/* CELL_SPURS_POLICY_MODULE_ERROR_* (firmware values). */
enum {
    GT6_SPURS_POLICY_ERROR_INVAL        = (int)0x80410802,
    GT6_SPURS_POLICY_ERROR_PERM         = (int)0x80410809,
    GT6_SPURS_POLICY_ERROR_BUSY         = (int)0x8041080A,
    GT6_SPURS_POLICY_ERROR_NULL_POINTER = (int)0x80410811,
};

/* cellVideoOut error values (firmware values; ps3recomp's cellVideoOut.h
 * uses a different base and would produce the wrong r3 here). */
enum {
    GT6_VIDEO_OUT_ERROR_ILLEGAL_PARAMETER     = (int)0x8002B222,
    GT6_VIDEO_OUT_ERROR_UNSUPPORTED_VIDEO_OUT = (int)0x8002B225,
};

/* CellSpurs field offsets (see the layout note above). */
enum {
    GT6_SPURS_WKL_FLAG          = 0x60,  /* CellSpursWorkloadFlag, 16 bytes */
    GT6_SPURS_WKL_FLAG_WORD     = 0x6C,  /* u32 flag inside that struct     */
    GT6_SPURS_WKL_FLAG_RECEIVER = 0x77,  /* u8, 0xFF = no receiver          */
    GT6_SPURS_MAX_WORKLOAD      = 32,    /* SPURS1 gives 16, SPURS2 32      */
};

static void gt6_cellSpursGetWorkloadFlag(ppu_context* ctx)
{
    const uint32_t spurs = (uint32_t)ctx->gpr[3];
    const uint32_t out   = (uint32_t)ctx->gpr[4];
    if (out)
        vm_write32(out, spurs + 0x60u);   /* &spurs->wklFlag */
    ctx->gpr[3] = 0;                      /* CELL_OK */
}

/*
 * int _cellSpursWorkloadFlagReceiver2(CellSpurs* spurs, uint32_t wid,
 *                                     uint32_t is_set, uint32_t debug);
 *
 * Marks `wid` as the workload that receives the workload flag (is_set != 0),
 * or removes it (is_set == 0). GT6 calls it from func_00B6E6AC (the engine's
 * SPURS job-queue bootstrap) with is_set=1 and debug=0, then immediately calls
 * cellSpursGetWorkloadFlag and caches the returned flag pointer. The return
 * value is not checked at that call site, but the side effects are real guest
 * state that the SPU kernel can read.
 *
 * The firmware rejects is_set=1 when another workload owns the receiver. Our
 * initialisation path leaves the byte zeroed instead of 0xFF, so a zero byte
 * with a zero flag word is normalised to "free" (see the guard below);
 * re-setting the same wid is treated as success (the operation is idempotent,
 * and a spurious BUSY would be worse than the firmware's stricter check).
 */
static void gt6_cellSpursWorkloadFlagReceiver2(ppu_context* ctx)
{
    const uint32_t spurs  = (uint32_t)ctx->gpr[3];
    const uint32_t wid    = (uint32_t)ctx->gpr[4];
    const uint32_t is_set = (uint32_t)ctx->gpr[5];
    const uint32_t debug  = (uint32_t)ctx->gpr[6];
    (void)debug;

    int32_t rc = 0;
    uint8_t receiver = 0xFF;

    if (!spurs) {
        rc = GT6_SPURS_POLICY_ERROR_NULL_POINTER;
    } else if (wid >= GT6_SPURS_MAX_WORKLOAD) {
        rc = GT6_SPURS_POLICY_ERROR_INVAL;
    } else {
        receiver = vm_read8((uint64_t)spurs + GT6_SPURS_WKL_FLAG_RECEIVER);

        /* ps3recomp's cellSpursInitialize() zeroes the instance and does not
         * write 0xFF here; the firmware does. A fresh instance also has a zero
         * flag word. Once this handler sets a receiver it writes 0xFFFFFFFF to
         * the flag word, so a zero receiver byte with a non-zero flag word
         * really means workload 0 owns the receiver. */
        if (receiver == 0 &&
            vm_read32((uint64_t)spurs + GT6_SPURS_WKL_FLAG_WORD) == 0)
            receiver = 0xFF;

        if (is_set) {
            if (receiver != 0xFF && receiver != (uint8_t)wid) {
                rc = GT6_SPURS_POLICY_ERROR_BUSY;
            } else {
                vm_write8((uint64_t)spurs + GT6_SPURS_WKL_FLAG_RECEIVER,
                          (uint8_t)wid);
                /* The receiver call resets the flag: not signalled. */
                vm_write32((uint64_t)spurs + GT6_SPURS_WKL_FLAG_WORD,
                           0xFFFFFFFFu);
            }
        } else {
            if (receiver != (uint8_t)wid) {
                rc = GT6_SPURS_POLICY_ERROR_PERM;
            } else {
                vm_write8((uint64_t)spurs + GT6_SPURS_WKL_FLAG_RECEIVER, 0xFFu);
                vm_write32((uint64_t)spurs + GT6_SPURS_WKL_FLAG_WORD,
                           0xFFFFFFFFu);
            }
        }
    }

    {
        static int logged = 0;
        if (!logged) {
            fprintf(stderr,
                    "[GT6] _cellSpursWorkloadFlagReceiver2(spurs=0x%08X "
                    "wid=%u set=%u) -> 0x%08X\n",
                    spurs, wid, is_set, (uint32_t)rc);
            logged = 1;
        }
    }

    ctx->gpr[3] = (uint64_t)(int64_t)(int32_t)rc;
}

/*
 * int cellVideoOutGetScreenSize(uint32_t videoOut, float* screenSize);
 *
 * Video-out IDs: 0 = CELL_VIDEO_OUT_PRIMARY, 1 = CELL_VIDEO_OUT_SECONDARY.
 * The port always has the primary output. GT6 calls this while building its
 * video configuration (func_00B7B034) with r3=0 and r4=&config+0x1C, then
 * reads the float back. Writing 24.0f gives the engine a plausible monitor
 * size instead of leaving the out-parameter at whatever the constructor put
 * there; the caller's sentinel check (0x4F0002B2) then keeps the value.
 */
static void gt6_cellVideoOutGetScreenSize(ppu_context* ctx)
{
    const uint32_t videoOut = (uint32_t)ctx->gpr[3];
    const uint32_t out      = (uint32_t)ctx->gpr[4];
    int32_t rc = 0;

    if (!out) {
        rc = GT6_VIDEO_OUT_ERROR_ILLEGAL_PARAMETER;
    } else if (videoOut != 0) {
        rc = GT6_VIDEO_OUT_ERROR_UNSUPPORTED_VIDEO_OUT;
    } else {
        /* 24.0f inches, big-endian guest float bits. */
        vm_write32(out, 0x41C00000u);
    }

    {
        static int logged = 0;
        if (!logged) {
            fprintf(stderr,
                    "[GT6] cellVideoOutGetScreenSize(videoOut=%u out=0x%08X) "
                    "-> 0x%08X (24.0 inch default)\n",
                    videoOut, out, (uint32_t)rc);
            logged = 1;
        }
    }

    ctx->gpr[3] = (uint64_t)(int64_t)(int32_t)rc;
}

/*
 * int cellUsbdSetThreadPriority2(int prio0, int prio1, int prio2);
 *
 * The engine's USB init wrapper (func_00803464) calls cellUsbdInit and then
 * this function with three clamped thread priorities (126, 127, 128 in the
 * GT6 call). The port has no USB host threads, so the priorities have no
 * effect; CELL_OK is the only sensible result. There are no out-parameters.
 * Exact argument semantics are not documented (RPCS3 also leaves this
 * UNIMPLEMENTED); three scalar integers is what the GT6 call site passes.
 */
static void gt6_cellUsbdSetThreadPriority2(ppu_context* ctx)
{
    const uint32_t prio0 = (uint32_t)ctx->gpr[3];
    const uint32_t prio1 = (uint32_t)ctx->gpr[4];
    const uint32_t prio2 = (uint32_t)ctx->gpr[5];

    {
        static int logged = 0;
        if (!logged) {
            fprintf(stderr,
                    "[GT6] cellUsbdSetThreadPriority2(%u, %u, %u) -> CELL_OK\n",
                    prio0, prio1, prio2);
            logged = 1;
        }
    }

    ctx->gpr[3] = 0;   /* CELL_OK */
}

/* -------------------------------------------------------------------------
 * Boot/presents probes: the pending project handoff.
 *
 * `main.adc` TOP -> `bootstrap_phase1_module.execBoot` -> `initMenuSystem`
 * -> `MGOM.initialize()` (script code 0x1CA61).  The native method wrapper at
 * 0x6C5424 calls `0x5F093C`, which allocates the menu context and starts the
 * menu worker thread (`0x6CD8F8` -> `0xA11F20` -> `sys_ppu_thread_create`,
 * entry OPD 0x14E0088 -> code 0xA122D4 -> 0xA12170).
 *
 * Measured in `work/size_run.err`, thread 35 (`vyENO`, arg=0x7FFECB00) is
 * created at line 263193 and stays alive until the shutdown join at line
 * 289338.  It is **not** the keep-alive/exit gate: the engine's 0xA11F20 wrote
 * arg+0x94 = 1 before create.  The worker's queue words at arg+0x80..0x88 are
 * the interesting part.
 *
 * `MGOM.start("boot")` (0x6C54DC -> 0x6C5478 -> 0x568C94) only stores the
 * pending project name at `manager+0x50` and sets `manager+0x48 = 1`.  It does
 * not open a file.  The missing event is whichever engine update consumes that
 * pending flag and calls the project loader (0x5FA338 -> 0x5F0424).  These
 * probes are read-only and identify that handoff; they never synthesize an
 * asset or call the presents functions.
 * ---------------------------------------------------------------------- */
static int gt6_boot_trace(void)
{
    static int on = -1;
    if (on < 0) {
        const char* e = getenv("GT6_BOOT_TRACE");
        on = (e && *e && *e != '0') ? 1 : 0;
    }
    return on;
}

static int gt6_guest_ptr_ok(uint32_t ea)
{
    /* Guest stacks can live below 0x80000000 (0x7FFE....) or in the
     * 0xCFE00000 main-stack window, so do not use a 2 GB cutoff here. */
    return ea >= 0x00010000u && ea < 0xFFFFFFF0u;
}

extern "C" void gt6_menu_worker_entry(ppu_context* ctx)
{
    const uint32_t arg = (uint32_t)ctx->gpr[3];
    if (!gt6_guest_ptr_ok(arg))
        return;
    if (!gt6_boot_trace())
        return;
    {
        static int n = 0;
        if (n++ >= 8) return;
    }

    const uint8_t keep = vm_read8((uint64_t)arg + 0x94u);
    fprintf(stderr,
            "[GT6] menu worker entry arg=0x%08X keep=%u "
            "q0=0x%08X q1=0x%08X q2=0x%08X\n",
            arg, (unsigned)keep,
            vm_read32((uint64_t)arg + 0x80u),
            vm_read32((uint64_t)arg + 0x84u),
            vm_read32((uint64_t)arg + 0x88u));
}

/* `0xA11F20` is the thread-create helper.  It sets the keep-alive byte on
 * `[*param_1+0x94]` before creating the worker.  Probe both pointers so a
 * mismatch between the object it writes and the thread arg is visible. */
extern "C" void gt6_menu_worker_prepare(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 8) return;
    }
    const uint32_t holder = (uint32_t)ctx->gpr[3];
    uint32_t obj = 0;
    unsigned flag = 0;
    if (gt6_guest_ptr_ok(holder)) {
        obj = vm_read32(holder);
        if (gt6_guest_ptr_ok(obj))
            flag = (unsigned)vm_read8((uint64_t)obj + 0x94u);
    }
    fprintf(stderr,
            "[GT6] menu worker prepare holder=0x%08X obj=0x%08X flag=%u\n",
            holder, obj, flag);
}

/* `MGOM.start(name)` wrapper (0x6C54DC -> 0x6C5478 -> 0x568C94).  This is
 * the script-side request that must be consumed by the menu worker above.
 * The wrapper's r4 is the HValue/string argument; try both the object's data
 * word and the raw pointer. */
extern "C" void gt6_mgom_start_probe(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 64) return;
    }
    const uint32_t name = (uint32_t)ctx->gpr[4];
    char s[96]; s[0] = 0;
    if (gt6_guest_ptr_ok(name)) {
        uint32_t data = vm_read32(name);
        if (!gt6_guest_ptr_ok(data) ||
            !gt6_read_guest_cstr(data, s, sizeof s))
            gt6_read_guest_cstr(name, s, sizeof s);
    }
    fprintf(stderr, "[GT6] MGOM.start name=0x%08X '%s'\n", name, s);
}

/* `MGOM.setProjectRoot(root)` wrapper (0x6C4DC0 -> 0x6C4A00 -> 0x5F0D64). */
extern "C" void gt6_mgom_setroot_probe(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 8) return;
    }
    const uint32_t root = (uint32_t)ctx->gpr[4];
    char s[96]; s[0] = 0;
    if (gt6_guest_ptr_ok(root)) {
        uint32_t data = vm_read32(root);
        if (!gt6_guest_ptr_ok(data) ||
            !gt6_read_guest_cstr(data, s, sizeof s))
            gt6_read_guest_cstr(root, s, sizeof s);
    }
    fprintf(stderr, "[GT6] MGOM.setProjectRoot arg=0x%08X '%s'\n", root, s);
}

/* Current-build first gate: `main::MGOM = MMenuGameObjectManager()`.
 * `0x6C4EC0`/`0x6C5064` register the class, `0x6C55DC` is the registered
 * factory/constructor, and `0x6C4A5C` allocates the 0x108-byte object and
 * stores it through the caller's output slot.  `0x9E2914` then clears a
 * pointer vector at `this+0x50..0x54`; the 16 null elements in
 * `work/bootui3_run.err` are what `0x9E911C` later dispatches.  These probes
 * are read-only and identify whether the constructor output stays null. */
extern "C" void gt6_mgom_class_probe(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 8) return;
    }
    fprintf(stderr,
            "[GT6] MGOM class register r3=0x%08X r4=0x%08X r5=0x%08X "
            "r6=0x%08X\n",
            (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4],
            (unsigned)ctx->gpr[5], (unsigned)ctx->gpr[6]);
}

extern "C" void gt6_mgom_factory_probe(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 8) return;
    }
    fprintf(stderr,
            "[GT6] MGOM factory r3=0x%08X r4=0x%08X r5=0x%08X r6=0x%08X\n",
            (unsigned)ctx->gpr[3], (unsigned)ctx->gpr[4],
            (unsigned)ctx->gpr[5], (unsigned)ctx->gpr[6]);
}

extern "C" void gt6_mgom_ctor_probe(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 8) return;
    }
    const uint32_t out = (uint32_t)ctx->gpr[3];
    fprintf(stderr,
            "[GT6] MGOM ctor out=0x%08X [out]=0x%08X r4=0x%08X r5=0x%08X\n",
            out,
            gt6_guest_ptr_ok(out) ? vm_read32((uint64_t)out) : 0u,
            (unsigned)ctx->gpr[4], (unsigned)ctx->gpr[5]);
}

extern "C" void gt6_mgom_vector_clear_probe(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 8) return;
    }
    const uint32_t self = (uint32_t)ctx->gpr[3];
    uint32_t begin = 0, end = 0;
    if (gt6_guest_ptr_ok(self)) {
        begin = vm_read32((uint64_t)self + 0x50u);
        end = vm_read32((uint64_t)self + 0x54u);
    }
    const unsigned count =
        (gt6_guest_ptr_ok(begin) && gt6_guest_ptr_ok(end) && end >= begin)
            ? (unsigned)((end - begin) / 4u) : 0u;
    fprintf(stderr,
            "[GT6] MGOM vector clear this=0x%08X begin=0x%08X end=0x%08X "
            "count=%u first=0x%08X\n",
            self, begin, end, count,
            gt6_guest_ptr_ok(begin) ? vm_read32(begin) : 0u);
}

/* Project loader `0x5FA338` (append ".mproject", call `0x5F0424`).  This is
 * the decisive probe: if it never runs with "boot", the pending request was
 * not consumed; if it runs, read the base/name and the following PFS opens. */
extern "C" void gt6_project_load_probe(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 16) return;
    }
    const uint32_t base = (uint32_t)ctx->gpr[4];
    const uint32_t name = (uint32_t)ctx->gpr[5];
    char sb[96]; sb[0] = 0;
    char sn[96]; sn[0] = 0;
    if (gt6_guest_ptr_ok(base)) {
        uint32_t d = vm_read32(base);
        if (!gt6_guest_ptr_ok(d) || !gt6_read_guest_cstr(d, sb, sizeof sb))
            gt6_read_guest_cstr(base, sb, sizeof sb);
    }
    if (gt6_guest_ptr_ok(name)) {
        uint32_t d = vm_read32(name);
        if (!gt6_guest_ptr_ok(d) || !gt6_read_guest_cstr(d, sn, sizeof sn))
            gt6_read_guest_cstr(name, sn, sizeof sn);
    }
    fprintf(stderr,
            "[GT6] project load this=0x%08X base=0x%08X '%s' "
            "name=0x%08X '%s'\n",
            (unsigned)ctx->gpr[3], base, sb, name, sn);
}

/* Pending-project setter `0x568C94`: the context stores the name at +0x50 and
 * raises the pending flag at +0x48.  It does not open any file itself. */
extern "C" void gt6_menu_project_request(ppu_context* ctx)
{
    if (!gt6_boot_trace()) return;
    {
        static int n = 0;
        if (n++ >= 64) return;
    }
    const uint32_t obj  = (uint32_t)ctx->gpr[3];
    const uint32_t name = (uint32_t)ctx->gpr[4];
    /* r4 is an HValue, not necessarily a C string; the `MGOM.start` probe
     * above already prints the raw 'boot' argument.  Log the two object words
     * only, so this cannot read a vtable as text. */
    fprintf(stderr,
            "[GT6] menu project request obj=0x%08X name=0x%08X "
            "word0=0x%08X word1=0x%08X pending_before=%u "
            "(0x568C94 sets +0x48=1 next)\n",
            obj, name,
            gt6_guest_ptr_ok(name) ? vm_read32((uint64_t)name) : 0u,
            gt6_guest_ptr_ok(name) ? vm_read32((uint64_t)name + 4u) : 0u,
            gt6_guest_ptr_ok(obj) ? (unsigned)vm_read32((uint64_t)obj + 0x48u) : 0u);
}

extern "C" void gt6_hle_overrides(void)
{
    ps3_hle_register_ctx(0xC765B995u, "cellSpursGetWorkloadFlag",
                         gt6_cellSpursGetWorkloadFlag);
    ps3_hle_register_ctx(0x2DDBCC0Au, "_cellSpursWorkloadFlagReceiver2",
                         gt6_cellSpursWorkloadFlagReceiver2);
    ps3_hle_register_ctx(0xFAA275A4u, "cellVideoOutGetScreenSize",
                         gt6_cellVideoOutGetScreenSize);
    ps3_hle_register_ctx(0x5C832BD7u, "cellUsbdSetThreadPriority2",
                         gt6_cellUsbdSetThreadPriority2);
}
