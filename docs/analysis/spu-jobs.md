# SPU job images — raw SPURS job binaries (GT6)

**Date:** 2026-10-31
**Scope:** lift and register the 15 raw SPURS job binaries captured from the
current native run under `work/spu_jobs/dump/` as
`spujob_<fingerprint>_<size>.bin`.
**Status:** all 15 lifted, registered under image ids 6..20, and compile-checked
with `clang -fsyntax-only`. The runtime build and `gt6.exe` were **not** run
(owner is testing).

## Bottom line

The runtime was dropping these jobs here:

```
[spu_workload] ERROR: SPURS job dispatch of an SPU program with no lifted image
(fp=0x... size=... owner=0x...)
```

Every one of the 15 dumps is a **raw job image, not an ELF**, and every one is
staged by the runtime at **LS 0**. The lifted entry is therefore the function at
LS `0x00000000`, and the registry key is the runtime's own fingerprint of the
raw file bytes (the value in the dump filename).

| | |
|---|---:|
| job images | 15 |
| total bytes | 470,800 |
| lifted functions | 6,562 |
| image ids | 6..20 |
| load base | `0x0` |
| registry function | `gt6_spu_register_jobs()` |
| registry file | `gt6/src/gen/spu_workloads_jobs.c` |
| generator | `scripts/lift-spu-jobs.ps1` |
| lifted sources | `gt6/generated/spu_lifted/jobs/<FP>/spu_recomp.{c,h}` |

## 1. Load base: why every job is lifted at `--base 0`

The miss is reported by `spu_workload_dispatch_job()` in
`third_party/ps3recomp/runtime/spu/spu_workload.c:1020`; the caller is the job
chain walker:

```c
/* libs/spurs/cellSpurs.c, jc_run_one_job() */
u64 ea_bin_raw = vm_read64(job_ea + JH_EA_BINARY);
...
spu_workload_dispatch_job(vm_base + ea_bin, size_bin, job_ea, size_desc);
```

`spu_workload_dispatch_job()` then calls `spu_run_spurs_job()` in
`runtime/spu/spurs_job.c`. That file documents and implements the placement:

```c
/* spurs_job.c:31-35 */
 * Load address: the job binary is position-independent (job_start_w_crt derives
 * its load delta with a brsl-to-next / subtract-link-time-address idiom), so jm2
 * may place it anywhere. We place it at LS 0 -- the lifted C is keyed to
 * link-time addresses, which makes the delta zero and the lifted branch targets
 * exact.

/* spurs_job.c:185-186 */
/* ---- binary at LS 0 (PIC, so delta 0 keeps the lifted addresses) ---- */
memcpy(ls, vm_base + ea_bin, size_bin);
```

The job is entered through the registered lifted function, not through an ELF
entry point. `spurs_job.c:382-383` installs the SPURS job ABI (`r3` =
`CellSpursJobContext2*`, `r4` = job descriptor), and the entry function runs from
the beginning of the image. Since the image is copied to LS 0 and the lifted
branch/lq/stqa addresses are literal LS offsets, the lift base **must** be 0:

- `spu_lifter.py --base 0` emits `spu_func_00000000` and literal LS offsets that
  match the staged image.
- `--base 0xA00` (the WWS PM base) or the `0x4000` guess from the earlier
  `docs/analysis/spu-spurs.md` note would shift every lifted LS access by that
  amount and would not match the runtime's staging. Those values belong to a
  different loader (policy module / taskset modules), not this dispatch path.

**Owner / EA evidence.** The job descriptor (`CellSpursJobHeader` at `job_ea`)
carries only `eaBinary` (`+0x00`) and `sizeBinary` (`+0x08`); it has **no load
base field** — jm2 chooses the placement, and this runtime chooses LS 0. The
`SPU_DUMP_MISS` dump file name stores only fingerprint and size, so the owner EA
from the error line is not persisted with the dump. No image in the set has a
nonzero link base: all 15 start with the same job-CRT prologue at offset 0 (the
four-word immediate/entry block followed by `xori $r80` / `br`), and across each
image 85–100% of `il`/`ila` immediates fall inside the image itself; the rest are
constants or references to SPURS-kernel/scratch LS addresses. There is no
cluster of internal addresses shifted by `0xA00` or `0x4000`.

If the runtime's job staging ever changes, these sources must be re-lifted at
the new base; the registry keys would stay the same but the C would not.

## 2. Fingerprint keys

`spu_workload_dispatch_job()` hashes exactly the bytes it was handed:

```c
uint64_t fp = spu_workload_fingerprint_cached(image, image_size);
```

`spu_workload_fingerprint()` is byte-serial FNV-1a-64 but seeds with
`1469598103934665603` (the standard offset basis `14695981039346656037` with a
digit dropped), not the standard basis. All 15 dump filenames were re-computed
byte-for-byte with that basis and match. Do **not** regenerate these keys with a
library FNV-1a-64 — the value would differ and the registration would silently
miss.

## 3. Images

Sorted by fingerprint (the generator assigns ids in this order). "First `.word`"
is the first instruction the lifter could not decode; it is where the data tail
starts producing false function seeds (see Risks).

| fingerprint | bytes | id | functions | coverage | `.word` | first `.word` |
|---|---:|---:|---:|---:|---:|---:|
| `1B6BDAC375C5438D` | 13,840 | 6 | 247 | 94.2% | 75 | `0x03170` |
| `2836AF271EDB4CB2` | 24,064 | 7 | 302 | 91.5% | 32 | `0x05430` |
| `459ACBD11F8BAFBE` | 13,328 | 8 | 208 | 94.4% | 22 | `0x030E0` |
| `48AF2BC79A72CB50` | 25,232 | 9 | 421 | 88.3% | 20 | `0x056F0` |
| `49C1D6C47E80AF43` | 24,720 | 10 | 426 | 90.8% | 18 | `0x05790` |
| `5DA195169669A5FF` | 72,464 | 11 | 609 | 98.4% | 17 | `0x11610` |
| `80435D36E623FAA0` | 19,488 | 12 | 325 | 92.6% | 14 | `0x04680` |
| `82D0BE145EC28AEE` | 17,424 | 13 | 282 | 95.6% | 33 | `0x04060` |
| `9804ABA84566F431` | 20,624 | 14 | 345 | 85.6% | 22 | `0x04480` |
| `ABD49FC58F53F368` | 9,488 | 15 | 196 | 94.6% | 5 | `0x02300` |
| `C1E79DAD1A299848` | 30,304 | 16 | 418 | 91.2% | 41 | `0x06A30` |
| `CB9BD0241BB0DE67` | 53,280 | 17 | 598 | 97.7% | 1,258 | `0x08D90` |
| `F523F26F69764538` | 64,912 | 18 | 886 | 95.5% | 296 | `0x0DD70` |
| `FDFFAAC1BCD5352E` | 34,704 | 19 | 637 | 93.7% | 62 | `0x07E40` |
| `FE031AF67ED048DE` | 46,928 | 20 | 662 | 78.5% | 55 | `0x090B0` |

The per-image `find_spu_functions.py` / `spu_lifter.py` logs are under
`work/spu_jobs/analysis/<FP>/find.log` and `lift.log`; the raw dumps remain in
`work/spu_jobs/dump/`.

## 4. Registry source (exact content)

`gt6/src/gen/spu_workloads_jobs.c` is generated by
`scripts/lift-spu-jobs.ps1`; do not hand-edit it.

```c
/* Raw SPURS job binaries GT6 dispatches through its job chains (image ids
 * 6..20).
 * GENERATED by scripts/lift-spu-jobs.ps1; do not edit by hand.
 *
 * The runtime fingerprints exactly the bytes cellSpurs hands to
 * spu_workload_dispatch_job(), so each key is the FNV-1a-64 value the
 * runtime computes (basis 1469598103934665603) over
 * work/spu_jobs/dump/spujob_<FP>_<size>.bin.
 *
 * Lifted at LS base 0: runtime/spu/spurs_job.c stages a job binary at LS 0
 * and enters the lifted function for address 0. Image id 5 is the WWS
 * job-manager PM (spu_workloads_pm.c); ids 1..4 are embedded SPU ELFs. */
#include "spu_workload.h"

extern void spu_begin_image(int image_id);
extern void job_1b6bdac3_spu_func_00000000(spu_context*);
extern void job_2836af27_spu_func_00000000(spu_context*);
extern void job_459acbd1_spu_func_00000000(spu_context*);
extern void job_48af2bc7_spu_func_00000000(spu_context*);
extern void job_49c1d6c4_spu_func_00000000(spu_context*);
extern void job_5da19516_spu_func_00000000(spu_context*);
extern void job_80435d36_spu_func_00000000(spu_context*);
extern void job_82d0be14_spu_func_00000000(spu_context*);
extern void job_9804aba8_spu_func_00000000(spu_context*);
extern void job_abd49fc5_spu_func_00000000(spu_context*);
extern void job_c1e79dad_spu_func_00000000(spu_context*);
extern void job_cb9bd024_spu_func_00000000(spu_context*);
extern void job_f523f26f_spu_func_00000000(spu_context*);
extern void job_fdffaac1_spu_func_00000000(spu_context*);
extern void job_fe031af6_spu_func_00000000(spu_context*);
extern void job_1b6bdac3_spu_recomp_register(void);
extern void job_2836af27_spu_recomp_register(void);
extern void job_459acbd1_spu_recomp_register(void);
extern void job_48af2bc7_spu_recomp_register(void);
extern void job_49c1d6c4_spu_recomp_register(void);
extern void job_5da19516_spu_recomp_register(void);
extern void job_80435d36_spu_recomp_register(void);
extern void job_82d0be14_spu_recomp_register(void);
extern void job_9804aba8_spu_recomp_register(void);
extern void job_abd49fc5_spu_recomp_register(void);
extern void job_c1e79dad_spu_recomp_register(void);
extern void job_cb9bd024_spu_recomp_register(void);
extern void job_f523f26f_spu_recomp_register(void);
extern void job_fdffaac1_spu_recomp_register(void);
extern void job_fe031af6_spu_recomp_register(void);

void gt6_spu_register_jobs(void)
{
    /* 1B6BDAC375C5438D, 13840 bytes, 247 lifted functions */
    spu_begin_image(6);
    job_1b6bdac3_spu_recomp_register();
    spu_workload_register_img(0x1B6BDAC375C5438DULL,
                              job_1b6bdac3_spu_func_00000000,
                              6, "spujob_1B6BDAC375C5438D");
    /* 2836AF271EDB4CB2, 24064 bytes, 302 lifted functions */
    spu_begin_image(7);
    job_2836af27_spu_recomp_register();
    spu_workload_register_img(0x2836AF271EDB4CB2ULL,
                              job_2836af27_spu_func_00000000,
                              7, "spujob_2836AF271EDB4CB2");
    /* 459ACBD11F8BAFBE, 13328 bytes, 208 lifted functions */
    spu_begin_image(8);
    job_459acbd1_spu_recomp_register();
    spu_workload_register_img(0x459ACBD11F8BAFBEULL,
                              job_459acbd1_spu_func_00000000,
                              8, "spujob_459ACBD11F8BAFBE");
    /* 48AF2BC79A72CB50, 25232 bytes, 421 lifted functions */
    spu_begin_image(9);
    job_48af2bc7_spu_recomp_register();
    spu_workload_register_img(0x48AF2BC79A72CB50ULL,
                              job_48af2bc7_spu_func_00000000,
                              9, "spujob_48AF2BC79A72CB50");
    /* 49C1D6C47E80AF43, 24720 bytes, 426 lifted functions */
    spu_begin_image(10);
    job_49c1d6c4_spu_recomp_register();
    spu_workload_register_img(0x49C1D6C47E80AF43ULL,
                              job_49c1d6c4_spu_func_00000000,
                              10, "spujob_49C1D6C47E80AF43");
    /* 5DA195169669A5FF, 72464 bytes, 609 lifted functions */
    spu_begin_image(11);
    job_5da19516_spu_recomp_register();
    spu_workload_register_img(0x5DA195169669A5FFULL,
                              job_5da19516_spu_func_00000000,
                              11, "spujob_5DA195169669A5FF");
    /* 80435D36E623FAA0, 19488 bytes, 325 lifted functions */
    spu_begin_image(12);
    job_80435d36_spu_recomp_register();
    spu_workload_register_img(0x80435D36E623FAA0ULL,
                              job_80435d36_spu_func_00000000,
                              12, "spujob_80435D36E623FAA0");
    /* 82D0BE145EC28AEE, 17424 bytes, 282 lifted functions */
    spu_begin_image(13);
    job_82d0be14_spu_recomp_register();
    spu_workload_register_img(0x82D0BE145EC28AEEULL,
                              job_82d0be14_spu_func_00000000,
                              13, "spujob_82D0BE145EC28AEE");
    /* 9804ABA84566F431, 20624 bytes, 345 lifted functions */
    spu_begin_image(14);
    job_9804aba8_spu_recomp_register();
    spu_workload_register_img(0x9804ABA84566F431ULL,
                              job_9804aba8_spu_func_00000000,
                              14, "spujob_9804ABA84566F431");
    /* ABD49FC58F53F368, 9488 bytes, 196 lifted functions */
    spu_begin_image(15);
    job_abd49fc5_spu_recomp_register();
    spu_workload_register_img(0xABD49FC58F53F368ULL,
                              job_abd49fc5_spu_func_00000000,
                              15, "spujob_ABD49FC58F53F368");
    /* C1E79DAD1A299848, 30304 bytes, 418 lifted functions */
    spu_begin_image(16);
    job_c1e79dad_spu_recomp_register();
    spu_workload_register_img(0xC1E79DAD1A299848ULL,
                              job_c1e79dad_spu_func_00000000,
                              16, "spujob_C1E79DAD1A299848");
    /* CB9BD0241BB0DE67, 53280 bytes, 598 lifted functions */
    spu_begin_image(17);
    job_cb9bd024_spu_recomp_register();
    spu_workload_register_img(0xCB9BD0241BB0DE67ULL,
                              job_cb9bd024_spu_func_00000000,
                              17, "spujob_CB9BD0241BB0DE67");
    /* F523F26F69764538, 64912 bytes, 886 lifted functions */
    spu_begin_image(18);
    job_f523f26f_spu_recomp_register();
    spu_workload_register_img(0xF523F26F69764538ULL,
                              job_f523f26f_spu_func_00000000,
                              18, "spujob_F523F26F69764538");
    /* FDFFAAC1BCD5352E, 34704 bytes, 637 lifted functions */
    spu_begin_image(19);
    job_fdffaac1_spu_recomp_register();
    spu_workload_register_img(0xFDFFAAC1BCD5352EULL,
                              job_fdffaac1_spu_func_00000000,
                              19, "spujob_FDFFAAC1BCD5352E");
    /* FE031AF67ED048DE, 46928 bytes, 662 lifted functions */
    spu_begin_image(20);
    job_fe031af6_spu_recomp_register();
    spu_workload_register_img(0xFE031AF67ED048DEULL,
                              job_fe031af6_spu_func_00000000,
                              20, "spujob_FE031AF67ED048DE");
    spu_begin_image(0);
}
```

Image id 5 remains the WWS job-manager PM (`spu_workloads_pm.c`); ids 1..4 are
the four embedded SPU ELFs (`spu_workloads.c`). No job id collides with those,
and 6..20 does not hit the runtime's special-cased image 22.

## 5. Integration

### 5.1 CMake (SPU source list)

`gt6/CMakeLists.txt` must compile the registry and the job-lifted sources:

```cmake
set(GT6_SPU_SOURCES
    "${CMAKE_SOURCE_DIR}/src/gen/spu_workloads.c"
    "${CMAKE_SOURCE_DIR}/src/gen/spu_workloads_pm.c"
    "${CMAKE_SOURCE_DIR}/src/gen/spu_workloads_jobs.c")
...
    file(GLOB GT6_SPU_LIFTED CONFIGURE_DEPENDS
        "${CMAKE_SOURCE_DIR}/generated/spu_lifted/*/spu_recomp.c")
    file(GLOB GT6_SPU_JOB_LIFTED CONFIGURE_DEPENDS
        "${CMAKE_SOURCE_DIR}/generated/spu_lifted/jobs/*/spu_recomp.c")
    list(LENGTH GT6_SPU_LIFTED N_SPU)
    list(LENGTH GT6_SPU_JOB_LIFTED N_SPU_JOBS)
    message(STATUS "lifted SPU images: ${N_SPU} + ${N_SPU_JOBS} runtime jobs")
    list(APPEND GT6_SPU_SOURCES ${GT6_SPU_LIFTED} ${GT6_SPU_JOB_LIFTED})
```

The jobs glob is required because those sources live one directory deeper than
the four ELFs and the PM. This tree is already wired this way; keep it inside the
SPU section only.

### 5.2 `gt6/src/main.cpp`

The declaration (near the other `gt6_spu_register_*` declarations):

```c
void gt6_spu_register_jobs(void);        /* 15 runtime SPURS job images, ids 6..20 */
```

The call, immediately after the PM registration:

```c
    gt6_spu_register_jobs();      /* SPURS job binaries captured from the running title */
```

The exact context is:

```c
    gt6_spu_register_all();   /* after the ELF load: fingerprints the loaded image */
    gt6_spu_register_pm_clean();  /* raw WWS PM at 0x013FFE00 (image id 5) */
    gt6_spu_register_jobs();      /* SPURS job binaries captured from the running title */
```

The patch is `patches/gt6-spu-jobs-main.patch`. At the time of writing the
working tree already contains both lines (the owner integrated them while this
job was being lifted); the patch is the canonical record for a tree that does not
have them. Do not re-add them if already present.

Call order matters only in that all registration happens before guest entry.
`gt6_spu_register_jobs()` calls `spu_begin_image(0)` at the end, like the PM
registration, so later registrations still start from the default image.

## 6. Verification performed

- All 15 dump filenames re-hashed with the runtime basis
  (`1469598103934665603`): fingerprint and size match for every file.
- `find_spu_functions.py --raw --base 0` on all 15; `spu_lifter.py --base 0
  --symbol-prefix job_<shortfp>_`; every generated source defines
  `job_<shortfp>_spu_func_00000000` and `job_<shortfp>_spu_recomp_register`.
- `clang -fsyntax-only --target=x86_64-w64-windows-gnu -std=c17
  -I third_party/ps3recomp/runtime/spu` on all 15 `spu_recomp.c` files and on
  `spu_workloads_jobs.c`: all exited 0.
- `scripts/build-gt6.ps1` was **not** run and `gt6.exe` was **not** run.

## 7. Risks and follow-ups

1. **Base is a runtime contract, not a property of the dump.** These images are
   lifted for LS 0 because `spurs_job.c` stages job binaries there. A future
   runtime change that stages jobs at a nonzero address (or a different job
   manager path) would require re-lifting at that base. There is no base field
   in the job header to consult; the placement is the loader's choice.
2. **Fingerprint basis is nonstandard.** The runtime seeds FNV-1a-64 with
   `1469598103934665603`. Recomputing with the real FNV basis produces a value
   that will never match. The generator validates every dump against the
   runtime basis before lifting; keep that check.
3. **Data tails are disassembled as code.** Job binaries have no symbols and no
   section table, so function starts come only from branch and pointer-table
   scans. Each image has a data tail near its end; the scanner seeds functions
   inside it and the lifter emits `.word`/`spu_unsupported` for undecodable data.
   Totals per image are in the table above (1,970 words overall; `CB9B...` alone
   contributes 1,258, `F523...` 296). These false functions are registered but
   are not reached unless an indirect branch or a genuine pointer table targets
   them. If a run stops in `spu_unsupported` at one of the listed first-`.word`
   offsets or above, add that image to the `$CodeEndByFp` map at the top of
   `scripts/lift-spu-jobs.ps1` (e.g. `'CB9BD0241BB0DE67' = 0x08D90`) and re-run
   it; the script then lifts with `--code-end` for that image and rewrites the
   registry, so the trim is reproducible. Do not apply a shared cutoff: the data
   boundary differs per image.
4. **Missing functions / hidden entry points.** The detector cannot see entry
   points that are only reachable through data (no `brsl`/`br`/`il`/`ila`
   reference). Symptoms are a runtime `spu_lookup` miss, a branch-to-0 log, or a
   halt. Remedies, in order of preference: add `--extra-funcs <addr,...>` to the
   lift, `--return-entries`, or `--force-indirect` for a misclassified return.
   Re-run `scripts/lift-spu-jobs.ps1` afterwards; it owns the sources and the
   registry, so the fix cannot be lost on relift.
5. **Descriptor size vs dump size.** The registry key is the runtime's
   `image_size` (from the job descriptor's `sizeBinary`, rounded to 16), which is
   exactly the amount dumped. If the title or a patch changes the descriptor
   size, the key changes; recapture the dump and regenerate. Do not truncate or
   pad a dump to a different size.
6. **Image ids are generated by sorted fingerprint order.** Adding a new
   `spujob_*.bin` shifts the ids of later jobs on regeneration. That is safe
   within one build (each begins its own image table), but any external tooling
   that hard-coded an id must be updated. Id 5 (PM) and 1..4 (ELFs) are never
   touched; 6..20 avoids the runtime's special image 22.
7. **Registration only fixes lookup, not job-manager staging.** The job still
   needs the runtime's `spu_run_spurs_job()` context setup at the top of LS
   (r3/r4, job descriptor copy, DMA tag). If a job now dispatches but halts
   immediately, inspect the job descriptor (`SPURS_JOB_DESCDUMP`), the chain
   command block (`SPURS_JOB_DUMP`), and the final LS (`SPU_LS_DUMP`), not the
   registry.
8. **`GT6_ENABLE_SPU` must be ON** for the lifted sources to be compiled. The
   registry translation unit is listed in `GT6_SPU_SOURCES` unconditionally, but
   it only links when its externs are present in the same build.
9. **Static registry capacity.** The job set adds 6,562 functions to the global
   SPU function registry, which is sized at 262,144 entries. That is ample, but
   a future job set of Yakuza-like size should re-check the cap.

## 8. Reproducing / relifting

```powershell
powershell -ExecutionPolicy Bypass -File scripts/lift-spu-jobs.ps1
# or with an explicit capture directory:
powershell -ExecutionPolicy Bypass -File scripts/lift-spu-jobs.ps1 `
    -DumpDir work/spu_jobs/dump
```

The script:

1. enumerates `spujob_<FP>_<size>.bin` in sorted order;
2. verifies each file's size and runtime fingerprint against its filename;
3. runs `find_spu_functions.py --raw --base 0` and `spu_lifter.py --base 0
   --symbol-prefix job_<shortfp>_` into
   `gt6/generated/spu_lifted/jobs/<FP>/`;
4. deletes and rebuilds the script-owned `gt6/generated/spu_lifted/jobs/` tree;
5. rewrites `gt6/src/gen/spu_workloads_jobs.c` with ids 6..N.

It is idempotent and deliberately owns the registry, so a relift cannot lose
the registrations.
