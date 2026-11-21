# EU disc (BCES01893): boot status

State at `ps3recomp v0.19.0` + `patches/ps3recomp-v0.19.0-gt6-eu-all.patch`:
the game boots, runs ~36 FPS and stops at the language-select dialog
(`eu-language-dialog.png`, 158 draw ops at frame 2500). It does not leave the
dialog on its own: with `PAD_SCRIPT=0.1:0x4000` (CROSS) the dialog closes and
"Sony Computer Entertainment presents" renders (`first-frame-sce.png`).

## What was needed to get here

| Blocker | Fix |
|---|---|
| Boot-2 validator: empty file cache (`func_00B5B260`), `userdb` read as SQLITE_NOTADB | hand edit of the lifted code, `patches/gt6-b5b260-cache-fill.patch.txt` (re-apply after every relift) |
| `cellMusicInitialize2` (NID `0xBE50B11E`) | stub in `gt6/src/stubs.cpp`: CELL_OK + INITIALIZE_RESULT callback, arg2 = pointer to result |
| net init (`getsockname`, NetCtl offline), `cellFiberPpuWaitFlag/CheckFlags` | stubs in `gt6/src/stubs.cpp`, NetCtl in the ps3recomp patch |
| HLE to guest callbacks (cellSaveData, sysutil, trophy) failed with ERR_FAILURE | `g_ps3_guest_caller` set in `gt6/src/main.cpp` |
| exec-range for exit-chain scan, 64-bit seek, lwcond generations, SPURS job chains | ps3recomp patch |
| RSX: INLINE_ARRAY, immediate draws, display-offset textures, zeta-as-texture (text via stencil glyphs), stale attribute-3 ignored | ps3recomp patch (`rsx_commands.c`, `rsx_d3d12_backend.c`) |

## Reproduce

```powershell
powershell -File scripts/setup-third-party.ps1 -Check
powershell -File scripts/build-gt6.ps1
powershell -File scripts/cap-gt6.ps1 -Name dlg -Frame 2500 -Seconds 150
```

`cap-gt6.ps1` writes `work/cap_<Name>/frame_00/{backbuffer.png,manifest.txt}`
and prints black/blue/white pixel shares. Frame 2500 needs ~90 s.

## Open

- **Dialog input.** The pad is polled (`cellPadGetInfo2`, `cellKbRead`, mouse info) but the
  highlight stays on row 1 and the pointer sits at the right edge of row 1. The
  consumer of pad state inside the dialog is unknown. Listener 6 (`func_00A395F0`) is a
  debug/key-sequence detector, not the dialog. Stick input and a fake mouse do not move
  the pointer.
- Row-1 hover highlight vs RPCS3 not verified.
- Real frames behind the dialog are untested; `FP_FORCE=1` shows geometry only.
- Reproducibility: function lists and the US `EMAIN.elf` hash are not committed; the
  `B5B260` edit is manual (see `repro-gaps.md`).
