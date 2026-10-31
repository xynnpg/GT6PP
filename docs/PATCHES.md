# Local patches to third-party checkouts

`third_party/` is not committed. These patches make the documented toolchain
(LLVM-MinGW/Clang on Windows) build the upstream code. Re-apply them after a
fresh clone.

## `patches/ps3recomp-mingw-seh.patch`

Applies to `third_party/ps3recomp` on `master` (v0.18.0 at the time of writing).

Two MinGW/Clang incompatibilities in `runtime/ppu/ppu_loader.cpp`:

1. **MSVC structured exception handling.** The stack sampler uses
   `__try { ... } __except (1) { ... }`, which MinGW/Clang does not implement.
   Replace it with a `VirtualQuery` readability check before the load. The guest
   stack is committed, so behavior is unchanged for normal samples; an
   unreadable slot is still skipped.
2. **Linkage conflict.** `ppu_resv_break` is declared `extern "C"` earlier in
   the file but defined `static inline` later. Clang rejects the mismatch.
   Give the definition external C linkage.

It also makes `cellFsLseek` use `_fseeki64`/`_ftelli64` on every Windows CRT,
not only MSVC. MinGW's `fseeko`/`off_t` can be 32-bit; GT6's `GT.VOL` is
15.4 GB, so a 32-bit seek would truncate. This is a correctness fix, not just a
compile fix.

Finally, the `PS3_EXIT_CHAIN` stack scan now recognises addresses up to
`0x00F908C4` (GT6's last executable byte) instead of `0x00900000`. Without it,
the exit-chain dump is empty for this title. Apply the patch and rebuild
`runtime/ppu/ppu_hle.cpp` after a fresh clone.

Apply:

```powershell
git -C third_party/ps3recomp apply ..\..\patches\ps3recomp-mingw-seh.patch
```

Or edit the two spots by hand; the patch is small.

## Build flag: `_WIN32_WINNT=0x0A00`

`runtime/spu/spu_workload.c` calls `GetCurrentThreadStackLimits`, which MinGW
headers only declare when `_WIN32_WINNT >= 0x0602`. The GT6 port's
`CMakeLists.txt` adds `_WIN32_WINNT=0x0A00` before `add_subdirectory`, and the
build scripts pass it in `CMAKE_C_FLAGS`/`CMAKE_CXX_FLAGS` as well.

## Upstreaming

Both changes are generic MinGW fixes and are worth sending upstream to
`sp00nznet/ps3recomp`. Until then, keep the patch file next to the port so a
fresh clone is one command away from building.
