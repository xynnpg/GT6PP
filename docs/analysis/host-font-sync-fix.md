# Host font open/read sync fix

Status: **proposal** (patch written, not applied; no build or `gt6.exe` run).
Scope: `gt6/src/stubs.cpp`, `tools/apply_gt6_post_lift.py`.
Evidence: `work/lwc_run.err` lines 794-806, `work/bootui3_run.err` lines 686-900,
and the lifted code at `gt6/generated/ppu_recomp_022.cpp` /
`ppu_recomp_023.cpp`.

## 1. What actually happens

The menu font preload reaches `ZFileStream::open` (`0x9F8E40`) with a host
virtual path, not with an `HFileReader`:

```
794: [bootui] file_open out=0xCFEFF890 path=0xCFEFF9D0 r5=0x00000001 r6=0x656E0000
795: [bootui] file_open arg=0xCFEFF9D0 s='/font/logo/menu_imagefont.bin'
796: [fileopen] 9F8E40 info=0xCFEFF9D0 info+3C=0xCFEFFAB0 info+40=0x00000000 file=0xCFEFF480
...
800: [fs] open '/dev_hdd0/game/BCUS98296/USRDIR/PDIPFS/K/2F' -> fd 3
801: [fileread] 9F4AA0 stream=0xCFEFF590 req=0xD0044C58 file=0xCFEFF480
802: [filehost] A08ED0 dev=0x01630B80 stream=0xCFEFF590 active=0x00 old=0x00000000
803: [LWCOND] signal tid=14 lwcond=0x016326A0 qid=0x4C000012 waiters=1 pending=0 lr=0x00A43038
804: [LWCOND] wait tid=14 lwcond=0x01632790 ...
806: [LWCOND] wait tid=4 lwcond=0x01632730 ... stk: A21CF8 A21D70 A08FC4 A09948 A1D98C A21E2C A09CA4 A09288 A21D78 A09308 A30518
```

The first host read (`0x9F4AA0` -> `FileDeviceHost` read `0xA08ED0`) is the last
progress. `0xA08ED0` stores the request at `dev+0x1C38/+0x1C3C`, signals
`dev+0x1BC8`, and waits on `dev+0x1BF8` through `0xA21D50`. The worker loop
around `0xA09288/A09308` never produces the completion the font loader needs.

Note on the brief: `0xCFEFF4A0` in line 799 is a **transient** wait in the open
path; it is woken (the trace continues to the `K/2F` open and the read). The
actual stall is the async `0xA08ED0` request on the font FileObject. The lwcond
trace stops printing after its 400-event budget, so the final wait on the host
device is not in the excerpt.

The `/font/vec/*.vec` opens also pass through `0x9F8E40`, but the measured ones
are served from the PFS cache (`[pfscache] 0xA40FBC`, e.g. `K/MR`, `K/4M`).
`menu_imagefont.bin` is the first one that falls through to the host device
read. The fix covers both kinds; it only changes reads for files that resolve
in the extracted tree.

## 2. Exact path, reader and FileObject layout

### Path

`0x9F8E40` receives the guest path in `r3` (C string; probe `[fileopen]
9F8E40 info=...` prints it). The host mapping is:

```
/font/logo/menu_imagefont.bin
  gt6_pfs_relpath()  -> font/logo/menu_imagefont.bin
  gt6_pfs_resolve()  -> work/gt6_vol/font/logo/menu_imagefont.bin   (229,891 bytes)

/font/vec/7seg.vec
  -> font/vec/7seg.vec -> work/gt6_vol/font/vec/7seg.vec            (10,512 bytes)
```

`gt6_pfs_root()` probes `work/gt6_vol/VER_INFO`, so the process must run from
the repository root (the existing overrides already assume this).
`gt6_pfs_resolve()` tries the direct relative path first, then the
`work/gt6_pfs_keymap.tsv` TOC map for cache-key opens
(`K/2F -> font/logo/menu_imagefont.bin`, `K/MR -> font/vec/7seg.vec`, ...).
No new path rules are needed.

### `0x9F8E40` signature

```
9F8E40(path /*r3*/, FileObject* /*r4*/, mode /*r5*/) -> FileObject* /*r3*/
```

It normalizes `path` with `0xA09FC8(path, stack[0x100], 0x100)`, walks the
device list, calls `device->vt[0x38](device, path, FileObject)`, logs
`[fileopen] ... file=<return>`, and on success calls `0x9F7D70(device,
FileObject)` to link the handle. On the measured path the device returns the
same `FileObject` pointer that was passed in `r4`; the later read at line 801
uses `file=0xCFEFF480`, the value logged by the open at line 796.

### `HFileReader` / `FileStream` / `FileObject`

The names matter because the brief's "reader+0x60" is relative to the
`FileStream` base, not to the `HFileReader` base.

| Offset | Meaning | Evidence |
|---|---|---|
| `HFileReader+0x30` | `FileStream` base (`basic_filebuf`) | `0x9F4130` is called with `reader+0x30` from `0x9F4218`; `0x9BB020` calls `0x9F4AA0(reader+0x30, ...)` |
| `FileStream+0x44` | `FileObject*` | `0x9F4130` writes `this+0x44 = FileObject`; `0x9F4AA0` reads `[stream+0x44]` |
| `FileStream+0x60` | embedded `FileObject` storage | `0x9F4130` passes `this+0x60` to `0x9F6BF4`; `[fileopen] 9F4130 this=0x7FFD6210 file=0x7FFD6270` |
| `HFileReader+0x74` | same `FileObject*` as `FileStream+0x44` | `reader+0x30+0x44`; `9BB020 reader=0x7FFD61E0`, `9F4130 this=0x7FFD6210`, `file=0x7FFD6270` |
| `HFileReader+0x90` | the embedded `FileObject` object | `reader+0x30+0x60` |
| `FileObject+0x40` | device pointer | `0x9F3E90` returns `[FileObject+0x40]` |
| `FileObject+0x5C` | owner `FileStream` | `0x9F4130` writes `FileObject+0x5C = this` |
| `FileObject+0xC0` | file size (`u64`) | `0x9F4B90` loads `[FileObject+0xC0]` as the size; `9F4130` has a post-open size fix-up |
| `FileObject+0x84` | open mode dword | `0x9F4130` writes `r6`; `0x9F4B90` branches on it |
| `HFileReader+0x18` | EOF flag | existing overrides |
| `HFileReader+0x1A8` | read-ahead buffer | existing overrides |
| `HFileReader+0x1AC` | read-ahead length | existing overrides |
| `HFileReader+0x1B0` | read-ahead position | existing overrides |
| `HFileReader+0x1B4` | guest-visible file offset | existing overrides |

So with `reader` = the `HFileReader` base used by `0x9BB020`:

```
FileObject* = vm_read32(reader + 0x74)
FileObject  = reader + 0x90   (object storage)
```

If `reader` means the `FileStream` base (`HFileReader+0x30`), then the object
is at `reader+0x60` and the pointer at `reader+0x44`. The proposal uses the
`HFileReader+0x74` form in `gt6_pfs_read_override`, because that function is
called with the `HFileReader` base.

### Read/seek/tell helpers (the non-HFileReader path)

```
0x9F4AA0(stream, req)            req = { u32 buf; u32 len; }
0x9F49D8(stream, origin, offset)
0x9F4930(stream) -> position
0x9F4878(stream, arg)            device vt[0x9C]; not used by mode 0
```

Each resolves the device with `0x9F3E90(stream)` (`[stream+0x44] ->
FileObject+0x40`) and calls `device->vt[0x90/0x94/0x98/0x9C]`. The host read
at `vt[0x90]` is `0xA08ED0`, the async submission. `0x9F4AA0` passes
`r5=req, r6=1`; `0xA08ED0` reads `[req]` and `[req+4]`, matching the two-word
request built by `0x9BB020` (`+0x70/+0x74`) and `0x9F4B90` (`+0x78/+0x7C`).

## 3. Can `gt6_pfs_path_hint` be installed at `0x9F8E40` or `0x9F79A8`?

**Not as-is.**

### `0x9F8E40`

Arguments are `(path, FileObject, mode)`, not `(reader, path)`. A call such as
`gt6_pfs_path_hint(r4, r3)` would install a **reader-keyed** slot whose key is
the `FileObject` pointer. `gt6_pfs_read_override` at `0x9BB020` looks up the
`HFileReader` base, so it would never match. It would also write the
`HFileReader` fields `+0x18/+0x1AC/+0x1B0/+0x1B4` into a `FileObject`, which
is the wrong object. A host-specific key is required.

### `0x9F79A8`

`0x9F79A8(out, path, mode)` stores `r3` (the caller's output/file-info
object, e.g. `0xCFEFF890`) and `r4` (path), then calls
`0x9F73E8 -> 0x9F73A0 -> 0x9F719C`. `0x9F719C` builds a **temporary**
`FileObject` at `sp+0x70` (constructor `0x9F4D24`), opens it, and copies only
`0x38` bytes from `FileObject+0xB0` back to the caller's object. The
`FileObject` used by the later read is therefore a temporary, not
`out+0x60`, and its address is not known at `0x9F79A8` entry. Keying a slot
by `out` would not match `[stream+0x44]` at `0x9F4AA0` time.

### `0x9F4130`

This is `HFileReader::open` and is already covered by the existing
`gt6_pfs_path_hint` call from `0x9BB11C`. The font preload **does not go
through it**: it goes `0x9F79A8 -> 0x9F73E8 -> 0x9F719C -> 0x9F6BF4 ->
0x9F8E40`. Adding another hint at `0x9F4130` would not help the font path.

## 4. Proposed patch

`patches/gt6-host-font-sync.patch` changes only:

* `gt6/src/stubs.cpp`
* `tools/apply_gt6_post_lift.py`

Generated sources are not edited. The post-lift script installs the hooks when
it is next run.

### 4.1 Slot key

`Gt6PfsSlot` gains a `file` key next to the existing `reader` key:

```
struct Gt6PfsSlot {
    uint32_t reader;   /* HFileReader key (0x9BB020), 0 for host slots */
    uint32_t file;     /* FileObject key (0x9F8E40), 0 for reader slots */
    ...
};
```

`GT6_PFS_SLOTS` grows from 8 to 16 because the font preload opens
`menu_imagefont.bin` plus about ten `.vec` faces, and the PFS reader slots
remain in the same table. `GT6_PFS_MAX_MB` still caps each file (default 64
MiB); the LRU evicts the oldest stream.

The existing loader body is factored into `gt6_pfs_install(rel, reader,
file)`. It still uses `gt6_pfs_resolve()` unchanged, so:

* PFS key/TOC behavior is preserved (`K/2F`, `K/MR`, ...).
* Reader slots remain keyed by the `HFileReader` base.
* `scripts/gt6/main.adc` is still excluded and owned by the boot-script
  override.
* `.adc` files that exist in `work/gt6_vol` continue to be served as plaintext
  through the same path resolver.

### 4.2 Host open key at `0x9F8E40`

A wrapper around the lifted function:

```
void func_009F8E40(ppu_context* ctx)
{
    const uint32_t _path = (uint32_t)ctx->gpr[3];
    const uint32_t _file = (uint32_t)ctx->gpr[4];
    gt6_pfs_host_open_prepare(_path, _file);   /* install slot keyed by r4 */
    gt6_orig_func_009F8E40(ctx);               /* real device open */
    gt6_pfs_host_open_commit(_file, (uint32_t)ctx->gpr[3]);
}
```

* `gt6_pfs_host_open_prepare` clears any old slot for that `FileObject`,
  reads the guest path, applies `gt6_pfs_relpath`, skips `main.adc`, and calls
  `gt6_pfs_install(rel, 0, file)`.
* `gt6_pfs_host_open_commit` re-keys to the returned pointer if a device ever
  returns a different object, drops the slot if the open failed, and writes
  `FileObject+0xC0 = size` **after** the open (the device open can leave it at
  zero for a host file; `0x9F4B90` uses that word as the stream size).

This is the post-open hook the brief asked for: the key is the returned
`FileObject` (which is also `r4` on every measured device open).

### 4.3 Read/seek/tell hooks keyed by `FileObject`

Post-lift entry hooks:

| Guest function | Hook |
|---|---|
| `0x9F4AA0` | `if (gt6_pfs_stream_read_override(ctx)) return;` |
| `0x9F49D8` | `if (gt6_pfs_stream_seek_override(ctx)) return;` |
| `0x9F4930` | `if (gt6_pfs_stream_tell_override(ctx)) return;` |

Each computes `file = vm_read32(stream+0x44)` and looks up
`gt6_pfs_find_file(file)`. Only files with a host slot are intercepted; every
other stream falls through to the original guest/device code.

* **Read**: `req = gpr[4]`, `out = vm_read32(req)`, `n = vm_read32(req+4)`.
  Copies `min(n, size-pos)` from the slot, advances `pos`, returns the count
  in `r3`. EOF returns 0 (a valid short read), not `-1`.
* **Seek**: `origin = gpr[4]`, `offset = gpr[5]`; supports `0/1/2`
  (`SET/CUR/END`), clamps to `[0,size]`, returns 0.
* **Tell**: returns `pos` in `r3`.

The existing `gt6_pfs_read_override` / `gt6_pfs_seek_override` at
`0x9BB020` / `0x9BAFE0` also fall back to `vm_read32(reader+0x74)` when no
reader-keyed slot exists. This covers `HFileReader` reads that bypass the
read-ahead override, while reader-keyed PFS slots keep priority.

### 4.4 Why this preserves the existing overrides

* The boot script still wins: `gt6_pfs_host_open_prepare` returns before
  installing anything for `scripts/gt6/main.adc`.
* PFS key/TOC lookups are unchanged: `gt6_pfs_install` calls the existing
  `gt6_pfs_resolve()` and `gt6_pfs_trace_toc()`.
* `.adc` plaintext: any other `.adc` present under `work/gt6_vol` is served by
  the same resolver, exactly as the `HFileReader` path hint already does.
* Reader slots (`Gt6PfsSlot.reader`) and host slots (`Gt6PfsSlot.file`) never
  collide: a lookup is either by `reader` or by `file`, and reader slots have
  `file == 0`, host slots have `reader == 0`.

## 5. Apply and verify

```
git apply patches/gt6-host-font-sync.patch
python tools/apply_gt6_post_lift.py gt6/generated
# rebuild and rerun gt6.exe (not done by this analysis)
```

The post-lift step is idempotent. It renames the lifted `func_009F8E40` to
`gt6_orig_func_009F8E40` and appends the wrapper, and inserts the three
stream hooks plus the five declarations in `ppu_recomp_022.cpp`.

Checks performed while writing this proposal (no build, no `gt6.exe`):

* `git apply --check --verbose patches/gt6-host-font-sync.patch` passes
  against `08f92ec`.
* The patched `tools/apply_gt6_post_lift.py` passes `python -m py_compile`.
* `add_host_open_wrapper()` and `add_script_hooks()` were run against a
  temporary copy of `ppu_recomp_022.cpp`: both are idempotent on a second
  run, and the six entry hooks plus the `gt6_orig_func_009F8E40` wrapper are
  present.

Expected traces with `GT6_PFS_TRACE=1`:

```
[hostopen] file=0xCFEFF480 path='font/logo/menu_imagefont.bin'
[GT6] pfs override: serving plaintext font/logo/menu_imagefont.bin (229891 bytes, file=0xCFEFF480, host open)
[hostov] stream=0xCFEFF590 file=0xCFEFF480 n=... pos=0/229891 font/logo/menu_imagefont.bin
```

The `[filehost] A08ED0` line should disappear for these reads. If a font is
opened but no `[hostov]` line appears, the path did not resolve (check
`work/gt6_vol/...` and `GT6_VOL_ROOT`) or the read used `0x9F4878` (see
below).

## 6. Open / unproven points

1. **`0x9F4878` is not hooked.** It calls device `vt[0x9C]` with a request
   pointer when `FileObject+0x84 == 1` (mode 1). The measured font open uses
   `0x9F6BF4`, which passes mode 0, and `0x9F4B90` then takes the `0x9F4AA0`
   branch. If a future font/fontset opens with mode 1, it can still reach the
   host device through `0x9F4878`. Semantics of `vt[0x9C]` were not proven,
   so it was deliberately left untouched.
2. **`0x9F3F2C` / `0x9F3EB0`** (device `vt[0x88]` / `vt[0x84]`) are not
   overridden. They returned before the measured stall, but they are not
   proven to be synchronous for every host file.
3. **Return pointer identity.** The measured device opens return the passed
   `FileObject` (`r4`) in `r3`. The commit hook re-keys if a device returns a
   different pointer, but if that pointer were a status value outside
   `0x00010000..0xFFFFFFEF`, the slot is dropped and the old async path
   returns. This is a deliberate safe fallback.
4. **Slot pressure.** 16 slots hold at most 16 extracted streams; the font
   preload uses about 12. `GT6_PFS_MAX_MB` still caps each allocation. If a
   future path opens more than 16 host streams before reading them all, LRU
   eviction can drop one. Increase `GT6_PFS_SLOTS` or close/reopen streams if
   that shows up.
5. **Concurrent open/read.** `prepare` installs the slot before the device
   open returns; the `FileObject` is not published to another thread until
   `0x9F8E40` returns, so the measured path cannot read a half-open slot.
   This relies on the device open not publishing the `FileObject` early; that
   is true in the measured trace but not proven for every device.
6. **`0xCFEFF4A0` in the brief.** It is not the final stall in
   `work/lwc_run.err` (line 799 is a transient wait, and the trace proceeds to
   the `K/2F` open and the first host read). The stall is the `0xA08ED0`
   async request. If a future trace still blocks on `0xCFEFF4A0` after this
   patch, that is a different open-path wait and needs its own trace.
7. **Alternate open dispatchers `0x9F8FA4` / `0x9F90E0` are not wrapped.**
   They call device `vt[0x34]` / `vt[0x30]` directly with `(path, mode)` and do
   not take a `FileObject*`. The measured font path uses `0x9F8E40`. If
   another loader uses these dispatchers, it can still reach the host device.

## 7. Address summary

| Address | Meaning |
|---|---|
| `0x9F8E40` | `open(path, FileObject*, mode) -> FileObject*` (host dispatch) |
| `0x9F6BF4` | `open(FileObject*, path)` wrapper used by `HFileReader` |
| `0x9F4130` | `HFileReader::open` (FileStream at `this+0x30`) |
| `0x9BB11C` | `HFileReader::open` body; existing path-hint hook |
| `0x9BB020` | `HFileReader::read`; existing read hook |
| `0x9BAFE0` | `HFileReader::seek`; existing seek hook |
| `0x9F4AA0` | `FileStream::read(stream, {buf,len})` -> device `vt[0x90]` |
| `0x9F49D8` | `FileStream::seek(stream, origin, offset)` -> device `vt[0x94]` |
| `0x9F4930` | `FileStream::tell(stream)` -> device `vt[0x98]` |
| `0x9F4878` | `FileStream` mode-1 helper -> device `vt[0x9C]` (**not hooked**) |
| `0x9F3E90` | `FileObject = [stream+0x44]`, return `[FileObject+0x40]` (device) |
| `0x9F7D70` | link `FileObject` into the device's open-handle list |
| `0xA08ED0` | `FileDeviceHost` read submission (async; the stall) |
| `0xA09288`/`0xA09308` | `FileDeviceHost` worker loop in the wait stack |
| `0xA21D50`/`0xA21E04` | lwmutex/lwcond wait and signal wrappers |
| `0x9F79A8` | boot-UI `open(out, path, mode)` wrapper (wrong key for a slot) |
| `0x9F719C` | builds the temporary `FileObject` for `0x9F79A8` |
| `0x8BD8C0` | boot-UI call site for `/font/logo/menu_imagefont.bin` |
