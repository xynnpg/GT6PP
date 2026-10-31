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

extern "C" {
void     vm_write8(uint64_t addr, uint8_t val);
void     vm_write32(uint64_t addr, uint32_t val);
uint8_t  vm_read8(uint64_t addr);
uint32_t vm_read32(uint64_t addr);
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
