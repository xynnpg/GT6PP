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
 * These overrides run after ppu_hle_register_all(), so they replace the
 * unresolved-import fallback for the same NID.
 */
#include "ppu_context.h"

extern "C" void vm_write32(uint64_t addr, uint32_t val);
extern "C" void ps3_hle_register_ctx(unsigned int nid, const char* name,
                                     void (*fn)(ppu_context*));

static void gt6_cellSpursGetWorkloadFlag(ppu_context* ctx)
{
    const uint32_t spurs = (uint32_t)ctx->gpr[3];
    const uint32_t out   = (uint32_t)ctx->gpr[4];
    if (out)
        vm_write32(out, spurs + 0x60u);   /* &spurs->wklFlag */
    ctx->gpr[3] = 0;                      /* CELL_OK */
}

extern "C" void gt6_hle_overrides(void)
{
    ps3_hle_register_ctx(0xC765B995u, "cellSpursGetWorkloadFlag",
                         gt6_cellSpursGetWorkloadFlag);
}
