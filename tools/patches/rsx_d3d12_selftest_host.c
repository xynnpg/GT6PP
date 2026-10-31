/*
 * ps3recomp - D3D12 backend self-test host harness
 *
 * Runs rsx_d3d12_backend_selftest() outside the emulator. The only emulator
 * pieces it supplies are the handful of cellGcm symbols the backend references
 * at link time; the self-test itself feeds fixed vertices through the rsx_backend
 * callbacks and needs neither vm_base nor the FIFO. A real D3D12 device and
 * swap chain are created, the triangle is drawn, and the backbuffer is read
 * back and checked numerically.
 *
 * Build/run with tools/patches/run_rsx_d3d12_selftest.ps1. Expected:
 *   [SELFTEST] legacy ... PASS
 *   [SELFTEST] vp     ... PASS
 *   [SELFTEST] RESULT: PASS
 *
 * The same test runs automatically in the emulator with
 *   RSX_D3D12_SELFTEST=1
 * (set RSX_D3D12_SELFTEST_VP=0 to test only the fixed-function path).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

typedef unsigned int  u32;
typedef unsigned char u8;

int rsx_d3d12_backend_init(u32 width, u32 height, const char* title);
void rsx_d3d12_backend_shutdown(void);
int rsx_d3d12_backend_pump_messages(void);
int rsx_d3d12_backend_selftest(void);

/* Symbols the backend references but that the self-test never takes a path
 * through (guest memory, notify/semaphore writes, texture upload registry). */
u8* vm_base = NULL;
uint32_t ppu_hle_inject_base = 0x20000000u;

void vm_write32(uint32_t a, uint32_t v) { (void)a; (void)v; }
u32 gcm_io_offset_to_ea(u32 io) { return io; }
unsigned long long ps3_ms_now(void) { return 0; }
void ps3_ms(const char* key) { (void)key; }

u32 cellGcmResolveOffset(u32 off) { return off; }
u32 cellGcmResolveIO(u32 off) { (void)off; return 0; }
u32 cellGcmResolveLocated(int local, u32 off) { (void)local; return off; }
int cellGcmOffsetIsDisplay(u32 off) { return off == 0; }
unsigned cellGcm_flip_request_count(void) { return 0; }
u32 rsx_find_vram_upload(u32 want) { (void)want; return 0; }
void rsx_reset_upload_claims(void) {}

int main(int argc, char** argv)
{
    /* The harness calls the entry point explicitly, so keep init from also
     * auto-running it if the caller's environment happens to set the gate. */
    _putenv_s("RSX_D3D12_SELFTEST", "0");

    if (argc > 1 && strcmp(argv[1], "--no-vp") == 0)
        _putenv_s("RSX_D3D12_SELFTEST_VP", "0");

    if (rsx_d3d12_backend_init(1280, 720, "rsx d3d12 selftest") != 0) {
        printf("backend init failed\n");
        return 2;
    }

    const int r = rsx_d3d12_backend_selftest();
    printf("selftest returned %d\n", r);
    fflush(stdout);

    /* Leave the window up briefly so a manual run shows the frame. */
    for (int i = 0; i < 120; i++) {
        if (rsx_d3d12_backend_pump_messages() != 0) break;
        Sleep(16);
    }

    rsx_d3d12_backend_shutdown();
    return r == 0 ? 0 : 1;
}
