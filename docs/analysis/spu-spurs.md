# SPU / SPURS verification — GT6 `BCUS98296` v1.00

**Date:** 2026-10-31
**Build:** `gt6/build/gt6.exe` (existing SPU-enabled build, 78,770 lifted PPU functions)
**Scope:** verify whether guest SPURS workloads reach the lifted SPU images, audit the
workload registry fingerprints against the images the guest actually passes to
`cellSpurs`, and capture/lift any unregistered images.

## Bottom line

The four lifted images are **not** the WWS job-manager policy module, although their own
registry keys are correct. The guest passes a **raw 12,160-byte (0x2F80) SPU policy
module at guest EA `0x013FFE00`**, fingerprint `0x5510DCB89C1E98C2`, to every
`cellSpursAddWorkload` call. That image is not in `gt6/src/gen/spu_workloads.c` and has
no lifted entry, so `spurs_resolve_pm()` refuses all eight workloads:

```
[cellSpurs] wid=0 PM NOT LIFTED (fp=0x5510DCB89C1E98C2 size=12160) -- workload will not run
...
[cellSpurs] wid=7 PM NOT LIFTED (fp=0x5510DCB89C1E98C2 size=12160) -- workload will not run
```

Consequently **0 SPU workloads were dispatched in this run**, **0 policy-module workers
ran**, and **0 job binaries / tasks were dispatched**. This is a deterministic lookup
failure, not a timing or scheduling hang. The run also exits through
`sys_process_exit(0)` before any workload is kicked, so fixing the PM is necessary but
not sufficient to see WWS work in the current boot.

## 1. Run and artifacts

Canonical clean run (only the requested environment variables; no extra diagnostics):

```powershell
$env:PS3_HEADLESS   = "1"
$env:PS3_VERBOSE    = "1"
$env:SPU_DUMP_MISS  = "work/spu_analysis/run_verify_20261031_114934/dump"

gt6\build\gt6.exe work\bin\EMAIN.elf
```

| Artifact | Path |
|---|---|
| canonical stdout | `work/spu_analysis/run_verify_20261031_114934/stdout.log` |
| canonical stderr | `work/spu_analysis/run_verify_20261031_114934/stderr.log` |
| captured PM dump | `work/spu_analysis/run_verify_20261031_114934/dump/spujob_5510DCB89C1E98C2_12160.bin` |
| earlier diagnostic run (`SPURS_TRACE`, `SPU_JOBEXEC`, `SPU_WORKER_TRACE`) | `work/spu_analysis/run_20261031_114433/` |
| PM wrapper ELF | `work/spu_analysis/pm_elf/pm_wwsjob_5510DCB89C1E98C2.elf` |
| `build_spu_workloads.py` PM lift | `work/spu_analysis/lifted/` |
| clean PM lift (data-word functions removed) | `work/spu_analysis/lifted_clean/` |
| inspection script | `work/spu_analysis/inspect_spu.py` |
| EMAIN reference scan | `work/spu_analysis/find_refs.py` |
| PM function lists | `work/spu_analysis/pm_functions.json`, `work/spu_analysis/pm_functions_clean.json` |

The earlier diagnostic run produced the same PM miss and no additional dispatch events;
`SPURS_TRACE`, `SPU_JOBEXEC` and `SPU_WORKER_TRACE` produced no SPU-side output because
no workload ever entered a policy module or job.

## 2. Observed dispatch counts

| Event | Count | Evidence |
|---|---:|---|
| `cellSpursAddWorkload` | 8 | stdout lines 72, 84, 96, 104, 118, 164, 178, 184 |
| workload PM resolution attempts | 8 (wid 0..7) | eight `PM NOT LIFTED` lines |
| workload PM resolved (registry hit) | **0** | no `PM resolved` lines |
| `spurs_pm_worker` / policy-module runs | **0** | no `[spurs-pm] RUN#` lines |
| `spu_workload_dispatch` (sync) | **0** | no `[spu_workload] dispatch` |
| `spu_workload_dispatch_async` (task) | **0** | no `[spu_workload] async image=` |
| `spu_workload_dispatch_job` (job) | **0** | no `[spurs-job] dispatch` |
| `cellSpursCreateTask` | 0 | no log line / API call |
| `cellSpursCreateJobChain`, Run/Kick/Join | 0 | no log line / API call |
| `SPU_DUMP_MISS` unique images | **1** | the PM only |
| exit | `sys_process_exit(0)` | stdout line 266 |

`[SPU] initialize(nspu=6, nrawspu=0)` at stderr line 561 is the raw `sys_spu` subsystem
initialisation, not a workload dispatch. The eight `PM NOT LIFTED` lines are at
`stdout.log:107, 112, 114, 116, 137, 165, 179, 185`.

## 3. Fingerprint audit

The runtime computes `spu_workload_fingerprint()` as the byte-serial FNV-1a-64 with
offset basis `1469598103934665603` (`runtime/spu/spu_workload.c:36-45`). The Python
helpers in `tools/spu_elf.py` and `tools/build_spu_workloads.py` use the same basis, so
the values below are directly comparable.

### 3.1 Images currently registered by the build

`gt6/src/gen/spu_workloads.c` has **8 registrations** (4 images, each keyed by its full
ELF extent and by its executable segment / `.text`):

| id | source | full fingerprint | `.text` fingerprint | entry | lifted funcs |
|---:|---|---|---|---:|---:|
| 1 | `spu_0000_at_011CE700` (`ps3spu.default`, `.objs/ps3spu.default.release.bui`) | `0x585A949A175194B9` | `0x009EF8ECD39A21AC` | `0x3050` | 108 |
| 2 | `spu_0001_at_01330800` (`ipc_spucore.elf`) | `0x4FC6769B02DF4F63` | `0x4A44368F3D9F7FFE` | `0x3050` | 159 |
| 3 | `spu_0002_at_01335B80` (`ipc_spucore_adv.elf`) | `0x32D946B4D3AACC32` | `0x223F07EA46400D1F` | `0x3050` | 396 |
| 4 | `spu_0003_at_0134C300` (`deep_spucore.elf`) | `0xE0EDF6ABA3654722` | `0xFDD8E988E979725B` | `0x3050` | 626 |

All eight registry keys were re-computed independently and match the bytes in
`work/analysis/spu/*.elf`. There is no internal fingerprint mismatch among these four
images. They are valid SPU ELFs, each linked at LS `0x3000` with entry `0x3050`.

### 3.2 Image the guest actually passes for WWS

| source | guest EA | size | fingerprint | in registry? |
|---|---:|---:|---|---|
| WWS job-manager PM (raw, not ELF) | `0x013FFE00` | `12160` (`0x2F80`) | `0x5510DCB89C1E98C2` | **no** |

The PM is byte-identical to `EMAIN.elf` file offset `0x13EFE00` (guest VA
`0x13FFE00`; the first PT_LOAD maps file offset `VA - 0x10000`). It has no ELF header
and no `SPUNAME`; its first words are SPU code:

```
43A67C02 42212C82 436F7502 43034382 ...
```

Its data tail contains the ASCII tag `WWSJ` at PM offset `0xC18` (LS `0x1618` when
loaded at LS `0xA00`), consistent with the WWS job manager.

The four registered ELFs are at guest VAs `0x011CE700`, `0x01330800`, `0x01335B80`,
`0x0134C300`. None of their full or `.text` fingerprints equals the PM fingerprint, and
the PM bytes are not a substring of any of them.

## 4. What the guest asks `cellSpurs` to run

All eight workloads use the same PM EA and size, with per-workload queue data:

| wid | workload name | PM EA | PM size | data EA | PM status |
|---:|---|---:|---:|---:|---|
| 0 | `Wws_Job` / `ElemSetRenderHP` | `0x013FFE00` | 12160 | `0x70016080` | not lifted |
| 1 | `Wws_Job` / `ElemSetRender` | `0x013FFE00` | 12160 | `0x70024080` | not lifted |
| 2 | `Wws_Job` / `ElemSetUpdate` | `0x013FFE00` | 12160 | `0x70032080` | not lifted |
| 3 | `Wws_Job` / `ElemSetGeneral` | `0x013FFE00` | 12160 | `0x70040080` | not lifted |
| 4 | `Wws_Job` / `ElemSetImmed` | `0x013FFE00` | 12160 | `0x7004E080` | not lifted |
| 5 | `Wws_Job` / `GPUSyncArray` | `0x013FFE00` | 12160 | `0x01681E00` | not lifted |
| 6 | `Wws_Job` / `GPURingArray` | `0x013FFE00` | 12160 | `0x01681C00` | not lifted |
| 7 | `Wws_Job` / `MdlSetJobArray` | `0x013FFE00` | 12160 | `0x015C7080` | not lifted |

The `pm` field is a guest EA, not a host pointer. `cellSpursAddWorkload` stores it and
`spurs_resolve_pm()` fingerprints exactly `sizePm` bytes at `vm_base + pm`.

## 5. Why nothing runs

The failure is in `third_party/ps3recomp/libs/spurs/cellSpurs.c`:

1. `spurs_resolve_pm(wid)` computes
   `spu_workload_fingerprint(vm_base + w->pm, w->sizePm)` and calls
   `spu_workload_find_img(fp, &image_id)` (`cellSpurs.c:1684-1686`).
2. The PM fingerprint `0x5510DCB89C1E98C2` is absent from the registry, so `r->fn` is
   NULL and the function logs `[cellSpurs] wid=%u PM NOT LIFTED ...` (`1687-1708`).
3. `spurs_kernel_thread()` does `if (!pm) continue;` (`cellSpurs.c:1795-1796`) before it
   consumes a ready count or signal. Thus the workload never gets a `SpursPmSlot`, a
   `spurs_pm_worker` never starts, and no `spu_run_policy_module()` / job dispatch
   happens.
4. `spurs_resolve_pm()` caches the negative result (`resolved = -1`), so a late
   registration cannot rescue the running instance. The PM must be registered before
   guest entry, with the other images.

This is a **hard, deterministic missing-image failure**, not an SPU hang. The absence of
`[spu_workload] dispatch MISS` is expected: this refusal happens in the cellSpurs PM
resolver before any of the two `spu_workload.c` miss paths. The `SPU_DUMP_MISS` file is
written by the cellSpurs-specific PM dump path (`cellSpurs.c:1694-1707`).

The current boot independently exits before any workload is kicked: there are no
`cellSpursReadyCountStore`, `cellSpursWorkloadSignal`, `CreateTask`, or job-chain calls
in the log. `sys_process_exit(0)` at stdout line 266 is the existing init-flag failure
described in `docs/HANDOFF.md`. Even with the PM registered, this boot would resolve the
eight PMs but still have no ready workload to run.

## 6. Are the four extracted images the right set?

**For the general set of embedded SPU ELFs: yes.** A scan of the whole `EMAIN.elf` found
exactly five ELF headers: the PPU ELF at offset 0 and four valid `EM_SPU` ELFs. There
are no additional embedded SPU ELFs. Their `.note.spu_name` values are:

- `spu_0000_at_011CE700` → `.objs/ps3spu.default.release.bui` (generic `ps3spu` core)
- `spu_0001_at_01330800` → `ipc_spucore.elf`
- `spu_0002_at_01335B80` → `ipc_spucore_adv.elf`
- `spu_0003_at_0134C300` → `deep_spucore.elf`

**For the WWS workloads: no.** These are ancillary SPU cores, not the WWS job-manager
policy module. They are linked at LS `0x3000`/entry `0x3050`, whereas the PM is a raw
image loaded at LS `0xA00` and entered at `0xA00`. No observed `cellSpursAddWorkload`,
`CreateTask`, or job-chain call in this boot uses their EAs. A constant scan of
`EMAIN.elf` (`work/spu_analysis/find_refs.py`) finds no 32- or 64-bit reference to any
of the four ELF VAs; the PM EA `0x013FFE00` appears once at file offset `0x14D64E8`,
consistent with a live data pointer. That scan cannot rule out a base+offset table, but
it is additional evidence that the four ELFs are not the WWS PM. The comment in
`gt6/CMakeLists.txt:56-58` claiming that all four SPURS workloads carry the same policy
module is misleading: the actual PM is a fifth, raw image and is missing from the
registry.

## 7. Captured PM and preliminary lift

The PM dump was wrapped in a minimal SPU ELF so the existing lift tool chain can consume
it, and lifted into a separate tree (**not** `gt6/generated`):

```powershell
python third_party/ps3recomp/tools/wrap_spu_elf.py `
  work/spu_analysis/run_verify_20261031_114934/dump/spujob_5510DCB89C1E98C2_12160.bin `
  --base 0xA00 --entry 0xA00 `
  --out work/spu_analysis/pm_elf/pm_wwsjob_5510DCB89C1E98C2.elf

python third_party/ps3recomp/tools/build_spu_workloads.py `
  --images work/spu_analysis/pm_elf `
  --lifted work/spu_analysis/lifted `
  --out work/spu_analysis/lifted/spu_workloads_pm.c `
  --register-fn gt6_spu_register_pm --title GT6-PM
```

Results:

| Property | Value |
|---|---|
| raw PM size | `12160` bytes (`0x2F80`) |
| raw PM fingerprint | `0x5510DCB89C1E98C2` |
| wrapper ELF full fingerprint | `0xF5342CF27C5098A2` |
| wrapper `.text` fingerprint | `0x5510DCB89C1E98C2` (equals raw PM) |
| wrapper entry | `0xA00` |
| detected functions | 194 |
| call targets | 36 |
| unsupported instructions | 4 × `.word` at LS `0x1610`, `0x1620`, `0x1630`, `0x1640` |
| function coverage | 9,192 / 12,160 bytes (75.6%) |

The four `.word` entries are **data**, not code: that region is the `WWSJ` table. A
filtered lift that removes those four false function starts has **190 functions and zero
unsupported instructions**, and compiles cleanly:

```powershell
python third_party/ps3recomp/tools/find_spu_functions.py `
  <pm.bin> --raw --base 0xA00 --code-out work/spu_analysis/pm_code.bin `
  --out work/spu_analysis/pm_functions.json

# remove starts 0x1610/0x1620/0x1630/0x1640, then:
python third_party/ps3recomp/tools/spu_lifter.py `
  work/spu_analysis/pm_code.bin --base 0xA00 `
  --functions work/spu_analysis/pm_functions_clean.json `
  --symbol-prefix pm_clean_ --output work/spu_analysis/lifted_clean
```

> **Length trap:** a descriptor table in `EMAIN.elf` near file offset `0x14D64E8`
> records `0x013FFE00` followed by `0x2F40` (12,096), but `cellSpursAddWorkload` asks
> for `0x2F80` (12,160). The extra `0x40` bytes are zero padding. The runtime hashes all
> 12,160 bytes, so the registry key **must** be the 0x2F80 fingerprint
> `0x5510DCB89C1E98C2`; hashing only `0x2F40` gives `0x183F405FFB5E56C2` and will miss.
> Extract the full `0x2F80` bytes from `SPU_DUMP_MISS`, not the descriptor length.

Both `spu_recomp.c` trees were compiled to objects with the project's LLVM-MinGW
`clang` and `-I third_party/ps3recomp/runtime/spu`; both returned 0. The generated
registration file uses image id 1 for its standalone case; **that id collides with
`ps3spu.default`** if copied verbatim into the port. Corrected copies with id 5 are at
`work/spu_analysis/lifted/spu_workloads_pm_id5.c` (from the 194-function generator
tree) and `work/spu_analysis/lifted_clean/spu_workloads_pm_id5.c` (from the clean
190-function tree). The clean registration is the one recommended for integration.

## 8. Root-cause hypotheses

**H1 — Confirmed: the WWS PM is not lifted/registered.**
`cellSpursAddWorkload` passes `pm=0x013FFE00`, size `12160`, fingerprint
`0x5510DCB89C1E98C2`. The registry contains only the four ancillary SPU ELFs. The
resolver returns NULL, `spurs_kernel_thread` skips every workload, and no SPU code runs.
This fully explains the 8/8 `PM NOT LIFTED` and zero dispatch.

**H2 — Contributing/boot-chain: no workload is kicked in this run.**
The log has zero ready-count/signal/create-task/job-chain calls. The process exits via
`sys_process_exit(0)` at the existing init gate. Therefore even a correct PM registration
will not produce WWS job execution until the boot-chain issue is fixed. The PM miss is a
latent blocker that becomes active immediately when the engine reaches SPU work.

**H3 — Future: job binaries are likely additional missing images.**
Once the PM runs, it will dispatch job binaries named by each workload's `data` queue.
Those are raw job blobs, not the four embedded ELFs. Expect further
`[spu_workload] dispatch MISS` / `SPU_DUMP_MISS` files in `spujob_*.bin` (or
`[spurs-job] dispatch MISS`) for those. This boot never got far enough to capture them.

**H4 — No fingerprint implementation mismatch.**
The four existing entries and the PM wrapper's `.text` entry were independently
recomputed with the runtime's exact FNV basis and match the generated registry values.
The problem is coverage, not a differing hash algorithm or size truncation.

## 9. Exact next fixes

1. **Add the raw PM to the image set.** Extract `EMAIN.elf` file offset `0x13EFE00`,
   length `0x2F80` to `pm_wwsjob.bin`; wrap it at base/entry `0xA00` (see section 7).
   Keep the wrapper's `.text` fingerprint `0x5510DCB89C1E98C2` as the real dispatch key.
2. **Register both keys under a non-colliding image id.** Use image id 5, not the
   standalone generator's id 1:
   ```c
   spu_begin_image(5);
   pm_..._spu_recomp_register();
   spu_workload_register_img(0xF5342CF27C5098A2ULL, pm_..._spu_func_00000A00, 5, "pm_wwsjob");
   spu_workload_register_img(0x5510DCB89C1E98C2ULL, pm_..._spu_func_00000A00, 5, "pm_wwsjob.text");
   spu_begin_image(0);
   ```
   Ready-to-review copies are `work/spu_analysis/lifted/spu_workloads_pm_id5.c` and
   `work/spu_analysis/lifted_clean/spu_workloads_pm_id5.c`.
3. **Prefer the clean 190-function lift.** Use
   `work/spu_analysis/lifted_clean/spu_workloads_pm_id5.c` with
   `work/spu_analysis/lifted_clean/spu_recomp.c`, or filter the `WWSJ` data region
   (`0x1610..0x1644`) from the 194-function tree before adding it to
   `gt6/generated/spu_lifted/`. The four `.word` functions must not be treated as
   reachable code.
4. **Wire it into the port.** Add the PM lifted source to
   `gt6/generated/spu_lifted/` (or regenerate the whole SPU set) and call the PM
   registration from `gt6/src/main.cpp` immediately after `gt6_spu_register_all()`.
   If regenerating all images, regenerate the registry so ids remain `1..4` for the four
   ancillary cores and `5` for the PM. Do not run the standalone `spu_workloads_pm.c`
   unchanged: its `spu_begin_image(1)` would overwrite image 1's branch table.
5. **Rebuild and verify the resolver.** Expected new log:
   ```
   [cellSpurs] wid=0 PM resolved (fp=0x5510DCB89C1E98C2 image=5)
   ...
   ```
   Then, once a workload is kicked:
   ```
   [spurs-pm] RUN#... wid=0 data=... image=5 entry=0xA00
   ```
6. **Then capture job binaries.** Run again with `SPU_DUMP_MISS` pointed at a fresh
   directory. Lift each new raw job blob into `work/spu_analysis/jobs/` using
   `wrap_spu_elf.py` at its actual LS base (the job staging base from the PM/descriptor,
   likely `0x4000`, not `0xA00`) plus `build_spu_workloads.py`, and register its raw
   fingerprint. Expect the first PM run to reveal these; they cannot be discovered from
   this boot because no job ever reached the dispatcher.
7. **Correct the build comment.** `gt6/CMakeLists.txt:56-58` should say the four
   embedded ELFs are ancillary SPU cores and that the WWS PM is a separate raw `0x2F80`
   image at guest `0x013FFE00`. This is a documentation fix, not part of the verified
   runtime failure.
8. **Keep the separate boot-chain work separate.** Even with the PM fixed, this boot
   still exits through `sys_process_exit(0)` before any kick. The init-flag gate and the
   three unresolved NIDs (`0xFAA275A4`, `0x2DDBCC0A`, `0x5C832BD7`) remain on the
   critical path to observing actual WWS job execution.

## 10. Verification checklist for the next run

- [ ] `gt6/src/gen/spu_workloads.c` contains `0x5510DCB89C1E98C2` (PM `.text` key).
- [ ] No `PM NOT LIFTED` for wids 0..7.
- [ ] Eight `PM resolved ... image=5` lines (or fewer, if only runnable workloads are
      resolved after a kick).
- [ ] `spurs_pm_worker` / `[spurs-pm] RUN#` lines appear after a real kick.
- [ ] `SPU_DUMP_MISS` directory contains PM (if not registered) and any new job blobs.
- [ ] `gt6/build/gt6.exe` still reaches the existing init gate; PM registration must not
      change PPU boot behaviour.

## Appendix — environment and evidence

Clean run environment:

```
PS3_HEADLESS=1
PS3_VERBOSE=1
SPU_DUMP_MISS=work/spu_analysis/run_verify_20261031_114934/dump
```

Key source locations:

- `runtime/spu/spu_workload.c:36-45` — FNV-1a-64 fingerprint
- `runtime/spu/spu_workload.c:306-346` — synchronous image dispatch
- `runtime/spu/spu_workload.c:1020-...` — job dispatch
- `runtime/spu/spu_workload.c:1485-...` — async task dispatch
- `libs/spurs/cellSpurs.c:1684-1708` — PM fingerprint / `PM NOT LIFTED` dump
- `libs/spurs/cellSpurs.c:1795-1796` — `if (!pm) continue;`
- `gt6/src/gen/spu_workloads.c:23-38` — current four-image registry
- `gt6/CMakeLists.txt:56-71` — SPU sources and the misleading comment

No files under `gt6/src/`, `gt6/generated/`, `gt6/CMakeLists.txt`,
`third_party/`, or `gt6/build/` were modified. The PM lift and all logs are under
`work/spu_analysis/`.
