# First boot: what to expect and how to debug

This is the checklist for the first run of `gt6.exe`. It assumes the build
succeeded and `work/bin/EMAIN.elf` exists.

## Normal startup log

A healthy beginning looks like this (exact formatting may vary):

```
[GT6] VM initialised (base=...)
[GT6] GCM control page + 256 MB RSX local memory committed
[GT6] cellFs root="PS3-Version/.../USRDIR" (disc -> .../PS3_GAME)
[GT6] Loading ELF: work/bin/EMAIN.elf
[ELF] Entry: 0x148E2E0, 8 program headers
[ELF] PT_TLS ...
[HLE] ps3recomp NID registry: ... handlers
[GT6] main stack ..., SP=...
[GT6] argv[0] = "/dev_bdvd/PS3_GAME/USRDIR/EMAIN.SELF" (argc=1)
[rsx] backend init skipped -- headless
[GT6] present thread started (60 Hz vblank/flip ticker)
[GT6] Executing 0x00010230 (TOC 0x14ED560)...
```

Then the guest runs. It will print `[cellFs]`/`[sys_fs]` opens, `[HLE]` calls,
and possibly `[spurs]` messages. The first stop is the useful result.

## The five most likely first failures

### 1. `entry 0x... is not in the lifted function table`

The generated table does not contain the entry. Check:

```powershell
python -c "import json; f=json.load(open('work/analysis/emain/EMAIN.functions.json')); print([x for x in f if int(x['start'],16) in (0x10230,0x10200)])"
```

If missing, re-run `ppu_loader.py` and the lifter. Do not hand-edit the table.

### 2. Guest page fault / access violation

The port installs a fault handler that commits guest pages on first touch. If it
still crashes, the log will name the host address and the guest address. Run
with `GT6_NO_FAULT_COMMIT=1` to make the first bad access fatal and easier to
locate. Check whether the guest pointer was translated through `vm_base`; HLE
code must never dereference a guest address directly.

### 3. `ps3_hle_call` missing NID

The generated HLE table only covers handlers the runtime implements. A missing
NID prints a diagnostic. Get the library/NID from
`work/analysis/emain/hle_stubs_named.json`:

```powershell
python -c "import json; a=json.load(open('work/analysis/emain/hle_stubs_named.json')); [print(e) for e in a if e['nid']=='0x...']"
```

Then choose one:

- implement the handler in `third_party/ps3recomp/libs/...` and regenerate the
  NID table;
- add a game-specific override in `gt6/src/stubs.cpp` (see the ps3recomp
  template for the `override_nid` pattern);
- stub it only if it has no output pointers and the game can tolerate failure.

### 4. Hang in `sys_cond_wait` / `sys_event_wait`

This is the GT5P Phase 16 shape: a worker is waiting for a signal nobody sends.
Use:

```powershell
$env:GT6_MAINSTACK="15"
$env:GT6_THREADS="1"
gt6\build\gt6.exe work\bin\EMAIN.elf
```

`GT6_MAINSTACK` prints the main thread's guest function and call stack;
`GT6_THREADS` prints every PPU thread and its last HLE call. The missing signal
is usually a module initialization order or a callback registration, not a
scheduler bug.

### 5. Volume read fails or returns garbage

The game opens `/dev_bdvd/PS3_GAME/USRDIR/GT.VOL` (the string is in
`EMAIN.elf`). Check:

- `gt6/GT.VOL` hardlink exists and points at the dumped 15.4 GB file;
- the `/dev_bdvd/` mapping in `main.cpp` points at `PS3_GAME`, not `USRDIR`;
- `sys_fs` uses `_stat64`/`_fseeki64` (it does on Windows);
- the guest is not asking for `PDIPFS` (this is a disc v1.00 dump).

`PS3_FSLOG=1` makes the runtime log path translation. Use it to see whether the
guest's path maps to the expected host file.

## Useful environment variables

| Variable | Effect |
|---|---|
| `PS3_HEADLESS=1` | no window; vblank/flip and FIFO still run |
| `PS3_VERBOSE=0` | reduce logging (important for timing) |
| `GT6_MAINSTACK=15` | print main thread location after 15 s |
| `GT6_THREADS=1` | print all PPU thread states every 2 s |
| `GT6_NO_PRESENT=1` | do not start the present thread |
| `GT6_NO_FAULT_COMMIT=1` | do not auto-commit faulted guest pages |
| `GT6_ARGS=...` | add guest argv tokens |
| `PS3_VFS_ROOT=...` | override the root for relative guest paths |
| `PS3_FSLOG=1` | log VFS path translation |
| `PS3_NO_GUEST_PTR_TRAP=1` | disable the low-4GB guest-pointer trap |

## Deep trace (use one at a time)

These are provided by ps3recomp and are documented in
`third_party/ps3recomp/docs/DIAGNOSTICS.md`:

| Variable | What it shows |
|---|---|
| `PS3_CALLTRACE=200` | first 200 indirect calls: target + r3/r4 |
| `PS3_HLE_TRACE=1` | every HLE call and its arguments |
| `PS3_HLE_UNRESOLVED=1` | unresolved NIDs |
| `PS3_HLE_PTRCHECK=1` | HLE returns a host pointer where the guest expects a guest address |
| `PS3_SCTRACE=1` | syscall entry/exit |
| `PS3_WAITBT=1` | one-shot guest stack dump per wait queue |
| `PS3_SYNCLOG=1` | which guest object a cond/mutex belongs to |
| `PS3_MEMTRACE=1` | guest memory allocation trace |
| `PS3_FSLOG=1` | VFS path translation |
| `PS3_EXIT_CHAIN=1` | guest call chain on `sys_process_exit` |
| `PS3_VERBOSE=0` | suppress most logging (set this when timing matters) |

Start with `PS3_HLE_UNRESOLVED=1` and `PS3_CALLTRACE=200`; add the others only
when the first trace points at a subsystem.

## Reading a guest address

Every lifted function is named `func_XXXXXXXX` after its guest address. The
function table is in `gt6/generated/ppu_recomp_table.cpp`. To find the function
containing an address, use the nearest entry at or below it:

```powershell
python -c "import re; a=0x00956D20; lines=open('gt6/generated/ppu_recomp_table.cpp').read().splitlines(); print([l for l in lines if '0x' in l][:5])"
```

Or use the runtime's `ppu_prof_resolve_host` / `ppu_guest_caller` diagnostics.

## What counts as progress

Do not chase a frame yet. The first useful result is:

1. the entry executes;
2. the guest reaches `main` or the first `cellSysutil`/`cellGcm` call;
3. the first `GT.VOL` open succeeds;
4. the stop is a named HLE function, not an access violation.

Record the log in `work/gt6_run.log` and update `docs/STATUS.md` with the first
stop and the last guest function.
