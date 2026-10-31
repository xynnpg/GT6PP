# Movie start trace: boot legal/presents -> OPENING PAMF

**Date:** 2026-10-31
**Target:** GT6 US `BCUS98296` v1.00; `work/gt6_vol/projects/gt6/boot/boot.adc`;
`work/bin/EMAIN.elf`; `work/rpcs3_oracle/rpcs3_input.log`; native HLE in
`third_party/ps3recomp` and `gt6/src/gen`.

**Scope:** read-only trace. No source edit, no relift, no build, no
`gt6.exe` run. Only this file was written. No key values or game payloads are
reproduced.

**Revision note:** the checkout used for this trace is `ea242bb`; the codec/HLE
files cited here are unchanged between `08f92ec` and `ea242bb`
(`git diff 08f92ec..ea242bb -- third_party/ps3recomp/libs/codec
gt6/src/gen/ppu_hle_nids.cpp` is empty).

**Address convention:** `EMAIN.elf` file offset = vaddr - `0x10000` for both
loadable segments. Script code offsets are ADCH code offsets inside the named
`.adc`, not vaddrs.

---

## 0. Verdict

The guest movie-start chain is:

```text
boot.adc boot(context) 0x1CEC0
  -> display_sequence -> display_sequence_gt6 0x1875F
  -> presents_sequence_common 0x16012            (legal/presents images)
  -> ... save-data / language / AdjustScreen gates ...
  -> MovieRoot.open(context) 0x20C3C
       -> SequenceUtil.startPageDirect(context, MovieRoot) 0x20C9A
       -> MovieRoot.onInitialize 0x20D19
       -> MovieFace.play_movie(context) 0x2106C
            -> MENUDB.query1("SELECT * FROM t_movie WHERE Name = 'OPENING'")
            -> movie_file = "/movies/" + FileName            (tv_10006_199556544)
            -> pdistd.Exist(movie_file + ".pam")
            -> key = Tv2.decodeContentsKey(movie.Key)
            -> self.setKey(key)
            -> self.load(context, movie_file) 0x21367
                 -> native MENU::mMovieFace / PDIEXT::PAMFStream load
                 -> cellPamfGetHeaderSize2 ... cellDmuxOpenEx ...
                    cellVdecOpenEx / cellAdecOpenEx ...
```

The opening file is `/movies/tv_10006_199556544.pam` (`t_movie.Name='OPENING'`,
FileName `tv_10006_199556544`), PFS key **`K/IP`**, GT.VOL offset
`0x2CAC000`, size `0x14ED5000` (351,096,832), PAMF `0041`, 3 streams
(AVC + 2x ATRAC3+), 191 AVC entry points, ~136 s.

**Current HLE cannot start the movie.** There are three independent reasons:

1. **14 imported NIDs are unregistered** (9 `cellPamf`, 4 `cellDmux`,
   1 `cellAdec`). The runtime's unresolved-NID default returns `CELL_OK`
   without writing out-parameters, so the title proceeds on fabricated state.
2. **The registered `cellPamf` parser uses an invented header layout**; for the
   opening it reports 0 streams, 0 EPs, start/end PTS 0 and mux rate 0.
3. **The demuxer is a one-AU stub**, and the current build has the real
   libavcodec path compiled out (`PS3RECOMP_FFMPEG_RUNTIME=OFF`). Even with a
   correct parser and demuxer, the first picture is a synthetic black
   1280x720 frame, not decoded video.

The smallest path to **start** the movie (load succeeds, decoders open) is P0
below: register the missing NIDs, rewrite `cellPamf` to the real PAMF 0041
layout, add `cellDmuxQueryAttr/OpenEx/QueryEsAttr`, and alias
`cellAdecOpenEx`. A real first frame additionally needs P1 (PAMF pack/PES
demux) and P2 (FFmpeg runtime). Advancing to the menu needs P3 (EOS/finish) or
the guest's own skip path.

The movie is downstream of the boot-project/PFS workstream: the port currently
does not load `boot.adc`, so `display_sequence_gt6` is never reached. That is a
prerequisite, not part of the codec HLE work.

---

## 1. Script trace (boot.adc)

`boot.adc` is `ADCH012`, 141,821 bytes, 1,682 symbols. The disassembly used here
is `work/boot_presents/boot_adc.txt`; the file's SHA-256 matches the extracted
copy in `docs/analysis/boot-presents-check.md` (`7149EF...F10AE`).

### 1.1 Legal/presents -> movie

| Stage | Function | Code | Key call |
|---|---|---|---|
| boot entry | `boot(context)` | `0x1CEC0` | starts `boot_sequence` thread, calls `display_sequence`, joins, then `start_project` |
| sequence setup | `boot_sequence_gt6` | `0x186E5` | `boot_sequence_common(context,"gt6")` |
| boot init | `boot_sequence_common` | `0x16606` | `initConfig`, `initSaveData` (`0x17AE3`), sets `init_save_data_done=1` (`0x17B57`/`0x17B79`), sets `sequence_done=1` (`0x186A7`/`0x186C9`) |
| display | `display_sequence_gt6` | `0x1875F` | first call `presents_sequence_common(context)` at `0x18798` |
| legal table | `presents_sequence_common` | `0x16012` | `PresentsRoot.open` (`0x162BC`), loop `changeImage` + `Thread.Sleep` |
| legal entries | `presents_table_scea` | `0x15E9F` | `common/JP/scei` 2 s, `common/notice` 2 s, `scea/JP/epilepsy` 4 s |
| save-data gate | `display_sequence_gt6` | `0x187C5` | waits while `boot_state.init_save_data_done` is false (`SET_STATE 2` at `0x187F1`) |
| sequence gate | `display_sequence_gt6` | `0x1881F` | waits while `boot_state.sequence_done` is false (`SET_STATE 2` at `0x1884B`) |
| language | `display_sequence_gt6` | `0x1893D` | optional `LanguageSelectRoot.open` |
| display area | `display_sequence_gt6` | `0x18A3D` | `AdjustScreenRoot.open`, wait `isDone` |
| save apply | `display_sequence_gt6` | `0x18B9A` | `applySaveData()` |
| vouchers | `display_sequence_gt6` | `0x18BB9` | `showVoucherMessages(context)` |
| skip decision | `display_sequence_gt6` | `0x18BF3` | `skipOpening = !GAME_STATUS.user_profile.option.opening_after_autoload`; if `boot_state.resume_gp != nil`, force `skipOpening=1` (`0x18C40`-`0x18C85`) |
| movie page | `MovieRoot.open` | `0x18DBE` | `MovieRoot.open(context)` only when `skipOpening` is false |
| page start | `MovieRoot.open` | `0x20C3C` | `SequenceUtil.startPageDirect(context, MovieRoot)` at `0x20C9A` |
| page init | `MovieRoot.onInitialize` | `0x20D19` | `MovieFace.play_movie(context)` at `0x20D6F` |
| wait | `display_sequence_gt6` | `0x18DF5` | polls `MovieRoot.isFinished`; `SET_STATE 2` until true |
| after movie | `boot(context)` | `0x1CFEF` | `start_project(context)` |

The `presents_sequence_common` call is the legal screen; the movie is not
started until after `init_save_data_done` and `sequence_done` are set by the
`boot_sequence` thread. A port that only runs the presents function but not the
boot sequence will stay parked at `0x187C5`/`0x1881F`.

### 1.2 MovieRoot / MovieFace

`MovieRoot.ad` module: `0x20BD1` source, `0x20BD8` module, `isFinished`
`0x20BF0`, `open` `0x20C3C`, `close` `0x20CB8` (sets `finished=true` at
`0x20CEB`/`0x20D04`), `onInitialize` `0x20D19`, `onFinalize` `0x20D91`,
`onActivate` `0x20E09`, `onCancel` `0x20EB4`, `onKeyPress` `0x20F64`.

`MovieFace` module: `0x2104F`; `play_movie` `0x2106C`; `stop_movie` `0x21385`;
`end_movie` `0x2140D`; `onMovieFinish` `0x21520`.

`play_movie` (code `0x2106C`) does exactly:

| Code | Action |
|---|---|
| `0x21099` | `audio_level = SoundUtil.GetMovieVolume()` |
| `0x210DC` | `audio_track = -1` |
| `0x21107` | `is_finish = false` |
| `0x21125`/`0x21148` | `movie = MENUDB.query1("SELECT * FROM t_movie WHERE Name = 'OPENING'")` |
| `0x21165`-`0x211AF` | if `movie == nil`: `self.end_movie(context)` |
| `0x211D5`-`0x211FF` | `movie_file = "/movies/" + movie.FileName` |
| `0x21213`-`0x21242` | `pdistd.Exist(movie_file + ".pam")`; if false: `end_movie` |
| `0x212A8`-`0x212DE` | `key = Tv2.decodeContentsKey(movie.Key)` |
| `0x212FB`-`0x21323` | `self.setKey(key)` |
| `0x21331`-`0x21367` | `self.load(context, movie_file)` |

`play_movie` does **not** check the return value of `self.load`; it just pops it
and reaches `SET_STATE 1` at `0x2137A`. This matters for the skip/failure
behaviour in section 5.4.

`end_movie` (`0x2140D`) calls `self.pause(true)`, `context.wait()` twice, sets
`self.is_finish`, then `MovieRoot.close(context)`, which sets `finished=true`.
`onKeyPress` (`0x20F64`) calls `end_movie` when `event.keysym == 65421`
(`0xFF8D`) at `0x20FB1`/`0x20FFB`; the oracle input run's Enter/Start at about
t=54 s is consistent with this handler (exact pad mapping not independently
verified). `onActivate`/`onCancel` also call `end_movie`.

### 1.3 Which engine call actually loads the movie

`MovieFace` is the boot project's movie module. Its `load`, `unload`, `pause`,
`setKey`, `setVideoSize`, etc. are not defined in `MovieRoot.ad`; they are the
native `MENU::mMovieFace` methods (RTTI `N4MENU10mMovieFaceE` at EMAIN file
`0x1042320`; `MMovieFace.cpp`/method names at file `0x10423A8`..`0x1042590`,
including `load` `0x10424A0`, `setKey` `0x1042578`, `pause` `0x10424F0`).

The native movie implementation is `PDIEXT::PAMFStream` (RTTI
`N6PDIEXT10PAMFStreamE` at EMAIN file `0x1068410`; vtable at vaddr `0x14782B0`,
typeinfo `0x1478334`, method slots from `0x14782B8`). Its load/parse function
is **`0x7FDD08`** (vtable slot 4, OPD `0x14D34D8`); its open/setup function is
**`0x7FFA60`**.

The exact binding from the script's `self.load` to `0x7FDD08` is inferred from
the class RTTI, the method-name table, and the function's behaviour; a direct
script->native call trace was not recovered. Flagged as unproven in section 7.

### 1.4 Movie file and PFS key

`docs/analysis/pamf-intro-fix.md` and `work/gt6_pfs_keymap.tsv`:

| Item | Value |
|---|---|
| `t_movie` row | `Name='OPENING'`, `FileName='tv_10006_199556544'`, 1920x1080, duration 136 |
| script path | `/movies/tv_10006_199556544.pam` |
| PFS key | `K/IP` |
| GT.VOL offset | `0x2CAC000` |
| size | `0x14ED5000` (351,096,832) |
| PAMF | `0041`, header `0x1000`, data `0x14ED4000` |
| streams | 0: AVC 1920x1088 (crop 4 -> 1080), 1: ATRAC3+ 2ch, 2: ATRAC3+ 6ch |
| EPs | 191 AVC entries |
| presentation | start 0x15CDE (0.992 s), end 0xBC4825 (137.10 s), mux 0x1D4C0 |

The oracle opens `PDIPFS_bdmark/K/IP`, `GT.VOL` at `0x2CAC000`, then
`K/IP.fdupm` and `K/IP.fdupi` before the first `cellPamf` call (log lines
87248-87513). The movie's decrypted/plaintext bytes reach `cellPamf`; the HLE
must not do key handling (section 7.2).

---

## 2. Native PAMFStream load path (EMAIN `0x7FDD08`)

`0x7FDD08` reads the file header, asks `cellPamf` for the header/data layout,
verifies it, initializes readers, and builds per-stream state. Call sites:

| Address | HLE call | Args as used by the guest |
|---|---|---|
| `0x7FDD8C` | `0x9F4AA0` file read | 0x800 bytes into the PAMF header buffer |
| `0x7FDDCC` | `cellPamfGetHeaderSize2` | `pAddr=header_buf`, `fileSize=[this+0x188]`, `attr=0`, `pSize=&[this+0x3B8]` |
| `0x7FDE00` | `cellPamfGetStreamOffsetAndSize` | `pOffset=&[this+0x3C0]`, `pSize=&[this+0x3C8]` |
| `0x7FDE0C`-`0x7FDE78` | malloc/memcpy/read | allocate `pSize`; copy first 0x800; read `pSize-0x800` at offset 0x800 |
| `0x7FDF50` | `cellPamfVerify` | `pAddr=header_buf`, `fileSize=[this+0x188]` |
| `0x7FDF68` -> `0x7FCD40` -> `0x7FCD60` | `cellPamfReaderInitialize` | reader = stack+0x90; `pAddr=header_buf`; `fileSize`; `attr=0` |
| `0x7FDF78` | `cellPamfReaderGetNumberOfStreams` | reader |
| `0x7FDF8C`/`0x7FDF9C` | `cellPamfReaderGetNumberOfSpecificStreams` | streamType 0x14 (video), 0x15 (audio) |
| `0x7FDFDC`-`0x7FE0E4` | per-stream loop | re-Initialize, `SetStreamWithIndex`, `GetStreamTypeAndChannel`, `GetPresentationStartTime`, `GetPresentationEndTime`, `GetMuxRateBound`, `GetEsFilterId`, `GetStreamInfo` |
| `0x7FE0E0`/`0x7FE17C` | `cellPamfReaderGetStreamInfo` | size 32 for AVC, size 8 for ATRAC3+ |
| `0x7FEA50` | `cellPamfReaderSetStreamWithTypeAndIndex` | seek path; not called in the captured run |
| `0x7FEA58` | `cellPamfReaderGetNumberOfEp` | seek path |
| `0x7FEA70` | `cellPamfReaderGetEpIteratorWithTimeStamp` | seek path |
| `0x7FEA84` | `cellPamfEpIteratorGetEp` | seek path |
| `0x7FEAB4` | `cellPamfEpIteratorMove` | seek path |

`0x7FDD08` returns 1 on success, 0 on any header/verify failure (the `li r3,0`
at `0x7FE1A8`). The script ignores that result (section 1.2).

### 2.1 Demux/decoder setup (`0x7FFA60`)

The same PAMFStream object then opens the demuxer and decoders. Guest call
sites (all direct `bl` to the import stubs):

| Address | HLE call | Stub |
|---|---|---|
| `0x80162C` | `cellDmuxQueryAttr` | `0xF90AE0` |
| `0x8016EC` | `cellDmuxOpenEx` | `0xF90B50` |
| `0x80008C` | `cellDmuxQueryEsAttr` | `0xF908E8` |
| `0x8000FC` | `cellDmuxEnableEs` (video) | `0xF90A70` |
| `0x8007E8` | `cellVdecQueryAttrEx` | `0xF91100` |
| `0x800220` | `cellVdecOpenEx` | `0xF90F78` |
| `0x80023C` | `cellVdecStartSeq` | `0xF910C8` |
| `0x8005B0` | `cellAdecQueryAttr` | `0xF911A8` |
| `0x800694` | `cellAdecOpenEx` | `0xF91218` |
| `0x800714` | `cellAdecStartSeq` | `0xF91170` |
| `0x800D00` | `cellDmuxSetStream` (chunk) | `0xF90920` |
| `0x7FD188` | `cellDmuxGetAu` | `0xF90A00` |
| `0x7FE578` | `cellVdecDecodeAu` | `0xF91020` |
| `0xEB7108` | `cellVdecGetPicItem` | `0xF90FE8` |
| `0xEB74D0` | `cellVdecGetPicture` | `0xF91058` |
| `0xEB8060` | `cellAdecDecodeAu` | `0xF91138` |
| `0xEB6CB4` / `0xEB6D6C` | `cellAdecGetPcmItem` / `GetPcm` | `0xF91288` / `0xF91250` |
| `0x7FCC04` | `cellVdecEndSeq` | `0xF91090` |
| `0x7FF5DC` | `cellVdecClose` | `0xF90FB0` |
| `0x7FF748` | `cellAdecClose` | `0xF911E0` |
| `0x7FD270` | `cellDmuxDisableEs` | `0xF90958` |
| `0x7FD2C8` | `cellDmuxResetEs` | `0xF90990` |
| `0x800C08` | `cellDmuxResetStream` | `0xF90A38` |
| `0x800F98` | `cellDmuxClose` | `0xF90AA8` |

At `0x801628` the guest builds a `CellDmuxType` with first word **1** and calls
`QueryAttr`; a new handler must accept that value rather than assuming the HLE
constant `CELL_DMUX_TYPE_PAMF=0`.

The `cellDmuxQueryAttr`/`QueryEsAttr` outputs are used as allocation sizes:
`0x801638` allocates the demuxer buffer from the first attribute word;
`0x80009C` allocates the ES buffer from the first ES-attribute word. A stub that
leaves these words zero results in a zero-size allocation (the guest adds 0x7F
and masks to 256-byte alignment) and a later overflow/failure; this is not a
safe "return CELL_OK" no-op.

**Callback ABI.** GT6's `cellDmuxOpenEx` and `cellDmuxEnableEs` pass a pointer
to a guest callback struct (`demuxerCb=*0xD0176BF0`, `esCb=*0xD0176A88`). The
current `cellDmux.c` API treats those positions as a raw function pointer and
argument (`cellDmuxOpen(type, res, cbFunc, cbArg, handle)`,
`cellDmuxEnableEs(..., esCbFunc, esCbArg, esHandle)`). A naive `OpenEx` alias
will shift the arguments and later call a stack address. Implement the
`OpenEx`/`EnableEs` ABI by reading `{cbFunc, cbArg}` from the guest struct
(the same shape `cellVdecOpen`/`cellAdecOpen` already use).

---

## 3. Oracle sequence and arguments

Source: `work/rpcs3_oracle/rpcs3_input.log`. The movie runs on
`PPU[0x1000034] Thread (PDI)`. All times are RPCS3 wall time.

| Time | Log line | Call / observation |
|---:|---:|---|
| 38.720 | 87250-87259 | `sys_fs_stat/open` `PDIPFS_bdmark/K/IP`; open GT.VOL, seek `0x2CAC000` |
| 38.724 | 87281-87325 | write `K/IP.fdupm` (0x2014 bytes); open/read it |
| 38.747 | 87500-87506 | open `K/IP.fdupi`, truncate to `0x14ED5000` |
| 38.748545 | 87513 | `cellPamfGetHeaderSize2(pAddr, fileSize=0x14ED5000, attr=0, pSize)` |
| 38.748549 | 87514-87515 | `cellPamfGetStreamOffsetAndSize` x2 |
| 38.748591 | 87516 | `cellPamfVerify(pAddr=0x427FA000, fileSize=0x14ED5000)` |
| 38.748594 | 87517 | `cellPamfReaderInitialize(pSelf=0xD01769E0, pAddr=0x427FA000, size, 0)` |
| 38.748596 | 87518 | `cellPamfReaderSetStreamWithIndex(0xD01769E0, 0)` |
| 38.748604 | 87519 | `cellPamfReaderGetNumberOfStreams(0xD01769E0)` |
| 38.748605 | 87520-87521 | `GetNumberOfSpecificStreams(20)`, `(21)` |
| 38.748609 | 87522-87524 | second reader `0xD0176A60`: Initialize, SetStreamWithIndex 0, SetStreamWithIndex 0 |
| 38.748619 | 87525 | `GetStreamTypeAndChannel(0xD0176A60, &type, &ch)` |
| 38.748621 | 87526-87528 | `GetPresentationStartTime`, `GetPresentationEndTime`, `GetMuxRateBound` |
| 38.748638 | 87529 | `GetEsFilterId` |
| 38.748643 | 87530-87531 | `GetStreamInfo(size=32)` -> `CELL_PAMF_STREAM_TYPE_AVC` |
| 38.748646 | 87532-87533 | re-Initialize reader, SetStreamWithIndex 0 |
| 38.748648 | 87534-87541 | `SetStreamWithIndex(1)`, `GetStreamTypeAndChannel`, presentation/mux, `GetEsFilterId`, `GetStreamInfo(size=8)` -> ATRAC3+ |
| 38.748673 | 87542-87551 | re-Initialize reader, `SetStreamWithIndex(2)`, same -> ATRAC3+ |
| 38.748778 | 87552 | `cellDmuxQueryAttr(demuxerType=0xD0176C04, demuxerAttr=0xD0176BF8)` |
| 38.748810 | 87554 | `cellDmuxOpenEx(type, resourceEx=0xD0176C10, cb=0xD0176BF0, handle=0x428124DC)` (RPCS3 internally `QueryAttr2` at 87555) |
| 38.750234 | 87561-87562 | `cellDmuxQueryEsAttr(type, filter, specificInfo, attr)` |
| 38.769061 | 87684 | `cellDmuxEnableEs(handle=0x45D98000, filter, resource=0xD0176A98, cb=0xD0176A88, specific=0xD0176AC8, esHandle)` |
| 38.769313 | 87691 | `cellVdecQueryAttrEx(type=0xD0176ABC, attr=0x428127C8)` |
| 38.899947 | 87987 | `cellVdecOpenEx(type, res=0xD0176B30, cb=0xD0176A90, handle=0x428127D8)` -> handle `0xF0000000` |
| 38.900451 | 87991 | `cellVdecStartSeq(0xF0000000)` |
| 38.900540 | 87994-88000 | second `QueryEsAttr`/`EnableEs` (audio) |
| 38.902488 | 88009 | `cellAdecQueryAttr(type=0xD0176A80, attr=0x42815ED8)` |
| 38.902619 | 88014-88015 | `cellAdecOpenEx(type=0x42815ED4, res=0x42815EEC, cb=0x42815EE4, handle=0x42815F3C)` -> handle `0x490C8000` |
| 38.902937 | 88026 | `cellAdecStartSeq(0x490C8000, param=0x42815F0C)` |
| 38.75-52.4 | - | playback: `cellDmuxSetStream`/`GetAu`, `cellVdecDecodeAu`/`GetPicItem`/`GetPicture`, `cellAdecDecodeAu`/`GetPcmItem`/`GetPcm` (not logged by this RPCS3 config) |
| 52.399 | 109417 | `cellDmuxResetStream(0x45D98000)`; RPCS3 returns `0x80010009` (race) |
| 52.399 | 109420 | `cellAdecEndSeq(0x490C8000)` |
| 52.399 | 109423 | `cellVdecStartSeq(0xF0000000)` (next sequence) |
| 52.402 | 109424-109429 | `cellVdecGetPicItem/GetPicture` fail `0x80610104` (no picture in new sequence) |
| 52.413 | 109436-109466 | `cellVdecEndSeq`, `cellVdecClose`, `cellDmuxDisableEs` x2, `cellAdecClose`, `cellDmuxClose` |

Expected return values (not printed by RPCS3): `CELL_OK=0` for all setup calls;
`GetNumberOfStreams=3`; `GetNumberOfSpecificStreams(20)=1`, `(21)=2`;
`GetPresentationStartTime=0x15CDE`; `GetPresentationEndTime=0xBC4825`;
`GetMuxRateBound=0x1D4C0`; `GetStreamInfo` writes a 32-byte AVC info block and
8-byte ATRAC3+ blocks. These values are from the decrypted PAMF 0041 header in
`docs/analysis/pamf-intro-fix.md` section 4, not from the RPCS3 log.

The first `cellPamfGetStreamOffsetAndSize` call passes `pSize=0` (null, line
87514); the handler must tolerate a null output pointer and write only
`pOffset`. The second call (87515) supplies both outputs.

The oracle's teardown at 52.4 s is consistent with the skip path: the input run
sent Enter at about t=54 s (scripted `run_input.ps1`), and the movie page's
`onKeyPress` -> `end_movie` -> `MovieRoot.close` path ran. The exact
input-to-keysym mapping is not proven (section 7).

---

## 4. Complete import inventory and current HLE state

Registration source: `gt6/src/gen/ppu_hle_nids.cpp`
(`cellDmux` at lines 1322-1332, `cellAdec` at 1225-1241, `cellPamf` at
1734-1747, `libvdec` at 2107-2114). "MISSING" means the exact GT6 NID is not
registered; the runtime then takes the unresolved-NID path
(`ppu_hle.cpp:185-212`), sets `r3=0`, and writes no out-parameters.

### 4.1 cellPamf (18 imports)

| NID | Function | Stub | Guest site | Current state |
|---|---|---|---|---|
| `0x90FC9A59` | `cellPamfGetHeaderSize2` | `0xF90DB8` | `0x7FDDCC` | **MISSING**; pSize unwritten |
| `0x44F5C9E3` | `cellPamfGetStreamOffsetAndSize` | `0xF90C68` | `0x7FDE00` | **MISSING**; offset/size unwritten |
| `0xD1A40EF4` | `cellPamfVerify` | `0xF90E98` | `0x7FDF50` | **MISSING**; no magic/size check |
| `0xB8436EE5` | `cellPamfReaderInitialize` | `0xF90E28` | `0x7FCD60` | registered; **wrong layout**, reports 0 streams |
| `0x37F723F7` | `cellPamfReaderGetNumberOfStreams` | `0xF90BF8` | `0x7FDF78` | registered; returns 0 |
| `0xD0230671` | `cellPamfReaderGetNumberOfSpecificStreams` | `0xF90E60` | `0x7FDF8C/9C` | registered; returns 0 (also ignores aggregate types 20/21) |
| `0x461534B4` | `cellPamfReaderSetStreamWithIndex` | `0xF90CA0` | `0x7FDFF0` | registered; fails because numStreams=0 |
| `0x9AB20793` | `cellPamfReaderGetStreamTypeAndChannel` | `0xF90DF0` | `0x7FE000` | **MISSING**; type/ch unwritten |
| `0x4DE501B1` | `cellPamfReaderGetPresentationStartTime` | `0xF90CD8` | `0x7FE00C` | registered; reads reserved 0x18, returns 0 |
| `0xF61609D6` | `cellPamfReaderGetPresentationEndTime` | `0xF90F40` | `0x7FE018` | registered; reads reserved 0x1C, returns 0 |
| `0xDB70296C` | `cellPamfReaderGetMuxRateBound` | `0xF90F08` | `0x7FE020` | registered; reads reserved 0x20, returns 0 |
| `0x71DF326A` | `cellPamfReaderGetEsFilterId` | `0xF90D80` | `0x7FE0C8/164` | **MISSING**; filter id unwritten |
| `0x67FD273B` | `cellPamfReaderGetStreamInfo` | `0xF90D48` | `0x7FE0E0/17C` | registered; wrong descriptor/offset, host-endian |
| `0x28B4E2C1` | `cellPamfReaderSetStreamWithTypeAndIndex` | `0xF90BC0` | `0x7FEA50` | **MISSING**; seek only |
| `0xD9EA3457` | `cellPamfReaderGetNumberOfEp` | `0xF90ED0` | `0x7FEA58` | registered; reads reserved 0x28, returns 0 |
| `0x439FBA17` | `cellPamfReaderGetEpIteratorWithTimeStamp` | `0xF90C30` | `0x7FEA70` | **MISSING**; seek only |
| `0x1ABEB9D6` | `cellPamfEpIteratorGetEp` | `0xF90B88` | `0x7FEA84` | **MISSING**; seek only |
| `0x50B83205` | `cellPamfEpIteratorMove` | `0xF90D10` | `0x7FEAB4` | **MISSING**; seek only |

Defects in `third_party/ps3recomp/libs/codec/cellPamf.c`:

* Header fields are read at `0x08`/`0x0C`/`0x10`/`0x14`/`0x18`/`0x1C`/`0x20`
  (`PAMF_OFF_*`, lines 34-44). The real PAMF 0041 header puts
  `header_size` sectors at `0x08`, `data_size` sectors at `0x0C`,
  `psmf_marks_offset/size` at `0x10`/`0x14` (both 0), and sequence info at
  `0x50`. For the opening this reads `numStreams=0`, `start/end=0`,
  `mux=0`, `ep_count=0`.
* Stream headers are 24 bytes (`PAMF_STREAM_DESC_SIZE`, line 50) at
  `[0x10]`; the real headers are 48-byte `PamfStreamHeader`s at `0x88`, each
  with `ep_offset` at `+0x08`, `ep_num` at `+0x0C`, and 32 bytes of codec info
  at `+0x10`.
* The SDK stream-type constants in `cellPamf.h:31-43` are invented (`AVC=0`,
  `ATRAC3PLUS=2`). Real coding types are `0x1B` AVC, `0x02` M2V, `0xDC`
  ATRAC3+, `0x80` LPCM, `0x81` AC-3; aggregate query types are `20` (video)
  and `21` (audio). `GetNumberOfSpecificStreams` therefore returns 0 even if
  the header were parsed.
* `cellPamf.h:67-98` structs are the wrong sizes: the guest asks for a 32-byte
  AVC info block and the HLE writes a 16-byte host struct; the audio fields are
  read from descriptor bytes 10/12 (EP fields), not the codec info. All
  `u16`/`u32` fields are written host-endian; the guest is big-endian.
* EP handling (`cellPamf.c:478-506`) reads `0x28`/`0x24` reserved fields and
  8-byte entries; the real EP table is per-stream (`ep_offset`/`ep_num`), with
  12-byte entries.
* Error constants are `0x806103xx` (`cellPamf.h:22-26`); the real family is
  `0x806105xx`. The guest may not check them, but the values are wrong.

### 4.2 cellDmux (12 imports)

| NID | Function | Stub | Guest site | Current state |
|---|---|---|---|---|
| `0xA2D4189B` | `cellDmuxQueryAttr` | `0xF90AE0` | `0x80162C` | **MISSING**; attr (allocation size) unwritten |
| `0xF6C23560` | `cellDmuxOpenEx` | `0xF90B50` | `0x8016EC` | **MISSING**; handle unwritten |
| `0x02170D1A` | `cellDmuxQueryEsAttr` | `0xF908E8` | `0x80008C` | **MISSING**; ES attr unwritten |
| `0x21D424F0` | `cellDmuxResetEs` | `0xF90990` | `0x7FD2C8` | **MISSING** |
| `0x04E7499F` | `cellDmuxSetStream` | `0xF90920` | `0x800D00` | registered; **whole-buffer one-AU stub** |
| `0x5D345DE9` | `cellDmuxResetStream` | `0xF90A38` | `0x800C08` | registered |
| `0x42C716B5` | `cellDmuxGetAu` | `0xF90A00` | `0x7FD188` | registered; **host pointer + host-endian** (see below) |
| `0x24EA6474` | `cellDmuxReleaseAu` | `0xF909C8` | `0x7FCF1C` | registered |
| `0x7B56DC3F` | `cellDmuxEnableEs` | `0xF90A70` | `0x8000FC` | registered; only works after a valid OpenEx |
| `0x05371C8D` | `cellDmuxDisableEs` | `0xF90958` | `0x7FD270` | registered |
| `0x8C692521` | `cellDmuxClose` | `0xF90AA8` | `0x800F98` | registered |
| `0xEBB3B2BD` | `cellDmuxFlushEs` | `0xF90B18` | no direct `bl` in the PAMFStream cluster | registered |

`cellDmux.c:149-215` presents the **entire input buffer** as one AU per enabled
ES and fires `DEMUX_DONE`. `cellVdecDecodeAu` therefore receives one AU per
`SetStream` chunk (potentially the whole 351 MB buffer) with no picture
boundaries or PTS.

`cellDmux.c:245-259` does `*auInfo = &s_es[esHandle].currentAu;` where
`auInfo` is a guest EA. That dereferences the guest EA as a host pointer and
returns a 64-bit host address; the guest at `0x7FD19C` truncates it to 32 bits
and copies 0x28 bytes. The stub also stores host-endian `u64` fields. This is a
source-level defect; it has not been exercised by GT6 because the port does not
reach the movie. A real `GetAu` must return a **guest-resident, big-endian**
`CellDmuxAuInfo` EA.

### 4.3 libvdec (8 imports, all registered)

| NID | Function | Stub | Guest site | Current state |
|---|---|---|---|---|
| `0xC982A84A` | `cellVdecQueryAttrEx` | `0xF91100` | `0x8007E8` | registered; fixed 1 MB attr, cmdDepth 4 |
| `0x0053E2D8` | `cellVdecOpenEx` | `0xF90F78` | `0x800220` | registered; `vdec_ff_open()` -> NULL with FFmpeg OFF |
| `0xC757C2AA` | `cellVdecStartSeq` | `0xF910C8` | `0x80023C`, `0xEB7D4C` | registered |
| `0x2BF4DDD2` | `cellVdecDecodeAu` | `0xF91020` | `0x7FE578` | registered; **dummy path** without FFmpeg |
| `0x17C702B9` | `cellVdecGetPicItem` | `0xF90FE8` | `0xEB7108` | registered; guest-resident item |
| `0x807C861A` | `cellVdecGetPicture` | `0xF91058` | `0xEB74D0` etc. | registered; **black 1280x720 frame** without FFmpeg |
| `0x824433F0` | `cellVdecEndSeq` | `0xF91090` | `0x7FCC04` | registered; emits SEQDONE |
| `0x16698E83` | `cellVdecClose` | `0xF90FB0` | `0x7FF5DC` | registered |

The real decode path exists in `cellVdec.c`/`vdec_ffmpeg.c`, but it is compiled
out: `third_party/ps3recomp/CMakeLists.txt:191` defaults
`PS3RECOMP_FFMPEG_RUNTIME` to OFF, `work/build_ps3recomp/CMakeCache.txt:273`
says `BOOL=OFF`, and `vdec_ffmpeg.c:225-236` returns NULL from `vdec_ff_open`.
`cellVdec.c:444-468` then emits a synthetic PICOUT with no pixels;
`cellVdec.c:626-644` copies a black frame. This is the difference between "the
movie API started" and "a real first frame".

### 4.4 cellAdec (8 imports)

| NID | Function | Stub | Guest site | Current state |
|---|---|---|---|---|
| `0x7E4A4A49` | `cellAdecQueryAttr` | `0xF911A8` | `0x8005B0` | registered; 256 KB attr |
| `0x8B5551A4` | `cellAdecOpenEx` | `0xF91218` | `0x800694` | **MISSING**; handle unwritten |
| `0x487B613E` | `cellAdecStartSeq` | `0xF91170` | `0x800714`, `0xEB8138` | registered; will see an unwritten handle |
| `0x1529E506` | `cellAdecDecodeAu` | `0xF91138` | `0xEB8060` | registered; **silence only** |
| `0x97FF2AF1` | `cellAdecGetPcm` | `0xF91250` | `0xEB6D6C` | registered |
| `0xBD75F78B` | `cellAdecGetPcmItem` | `0xF91288` | `0xEB6CB4` | registered |
| `0xE2EA549B` | `cellAdecEndSeq` | `0xF912C0` | `0xEB8108` | registered |
| `0x847D2380` | `cellAdecClose` | `0xF911E0` | `0x7FF748` | registered |

The port registers `cellAdecOpen` (`0xD00A6988`) but GT6 imports
`cellAdecOpenEx` (`0x8B5551A4`), which is missing everywhere in the tree.
`cellAdec.c:228-285` writes zero PCM and returns a valid PCM item (silence);
`cellAdecAtrac3p.c:1-7` is explicitly a silence stub. The earlier
`pamf-intro-fix.md` claim that `cellAdec` has an ATRAC3+ decoder is incorrect;
the only real ATRAC3+ code is `cellAtrac` (music), not `cellAdec`.

### 4.5 Args and expected returns for the missing handlers

Signatures below are the shapes GT6 uses at the cited guest call sites. "0"
means `CELL_OK`; the values in the right column are the correct PAMF 0041
results for the opening, not values printed by RPCS3.

| NID | Handler | Arguments as used by GT6 | Expected result |
|---|---|---|---|
| `0x90FC9A59` | `cellPamfGetHeaderSize2` | `(pAddr, fileSize, attribute=0, pSize)` | 0; `*pSize=0x1000` |
| `0x44F5C9E3` | `cellPamfGetStreamOffsetAndSize` | `(pAddr, fileSize, pOffset, pSize)` | 0; `*pOffset=0x1000`, `*pSize=0x14ED4000`; tolerate `pSize=NULL` |
| `0xD1A40EF4` | `cellPamfVerify` | `(pAddr, fileSize)` | 0 if magic/version/sizes match |
| `0x9AB20793` | `cellPamfReaderGetStreamTypeAndChannel` | `(reader, &type, &channel)` | 0; type `0x1B`/`0xDC`, channel 0/1/2 |
| `0x71DF326A` | `cellPamfReaderGetEsFilterId` | `(reader, &filterId)` | 0; filter id for the current stream |
| `0x28B4E2C1` | `cellPamfReaderSetStreamWithTypeAndIndex` | `(reader, type, index)` | 0; selects the stream (seek) |
| `0x439FBA17` | `cellPamfReaderGetEpIteratorWithTimeStamp` | `(reader, &timestamp, &iterator)` | 0; iterator at/before timestamp |
| `0x1ABEB9D6` | `cellPamfEpIteratorGetEp` | `(iterator, &ep)` | 0; current EP |
| `0x50B83205` | `cellPamfEpIteratorMove` | `(iterator, direction, &ep)` | 1 when moved (guest compares `r3==1`), 0 otherwise |
| `0xA2D4189B` | `cellDmuxQueryAttr` | `(type, &attr)` | 0; first attr word nonzero (demuxer allocation size) |
| `0xF6C23560` | `cellDmuxOpenEx` | `(type, resourceEx, cb, handle)` | 0; `*handle` valid; read `{cbFunc,cbArg}` from `cb` |
| `0x02170D1A` | `cellDmuxQueryEsAttr` | `(type, filterId, specificInfo, &attr)` | 0; first attr word nonzero (ES allocation size) |
| `0x21D424F0` | `cellDmuxResetEs` | `(esHandle)` | 0 |
| `0x8B5551A4` | `cellAdecOpenEx` | `(type, resource, cb, handle)` | 0; `*handle` valid; alias to `cellAdecOpen` |

---

## 5. Minimum HLE, ranked

### P0 - Start the movie (header/lifecycle only)

The definition of "start" here: `PAMFStream::load` returns 1, the demuxer and
decoder handles exist, `cellDmuxEnableEs`/`cellVdecOpenEx`/`cellAdecOpenEx`
return success, and the script reaches the playback loop. No frame needs to be
decoded.

1. **Register the 14 missing NIDs**: 9 `cellPamf`
   (`0x90FC9A59`, `0x44F5C9E3`, `0xD1A40EF4`, `0x9AB20793`, `0x71DF326A`,
   `0x28B4E2C1`, `0x439FBA17`, `0x1ABEB9D6`, `0x50B83205`), 4 `cellDmux`
   (`0xA2D4189B`, `0xF6C23560`, `0x02170D1A`, `0x21D424F0`), and
   `cellAdecOpenEx` (`0x8B5551A4`). Do not leave them on the fake-`CELL_OK`
   path; that path never writes the out-parameters.
2. **Rewrite `cellPamf` to PAMF 0041**:
   * `header_size=be32(0x08)*0x800`, `data_size=be32(0x0C)*0x800`;
   * sequence info at `0x50`, grouping period at `0x70`, group at `0x82`;
   * 3 stream headers (48 bytes) at `0x88`; `ep_offset`/`ep_num` at `+0x08`/
     `+0x0C`; 12-byte EP entries;
   * start/end PTS from `0x56`/`0x58` and `0x5C`/`0x5E`; mux from `0x62`;
   * real SDK coding types (`0x1B`, `0x02`, `0xDC`, `0x80`, `0x81`) and
     aggregate video/audio types 20/21;
   * 32-byte AVC info and 8-byte ATRAC3+ info, guest big-endian.
3. **Implement `cellPamfGetHeaderSize2` / `GetStreamOffsetAndSize` / `Verify`**
   with the header/data values above. `GetHeaderSize2` returns the 0x1000
   header, not the whole file; the guest allocates 0x1000 and reads the second
   0x800 bytes in the block at `0x7FDE0C`-`0x7FDE78`.
4. **Implement `cellDmuxQueryAttr`, `cellDmuxOpenEx`, `cellDmuxQueryEsAttr`,
   `cellDmuxResetEs`** as thin setup functions. Return a nonzero memory size
   in the first attribute word (the guest allocates from it), accept
   `CellDmuxType` word 1, and return a handle that `EnableEs`/`SetStream`/
   `GetAu` recognize. `OpenEx` must read the guest `CellDmuxCb` struct
   (`{cbFunc, cbArg}`) and use the existing slot setup; do not call the
   5-argument `cellDmuxOpen` with the 4-argument `OpenEx` register layout.
   `QueryAttr2` is internal to RPCS3, not a GT6 import.
5. **Alias `cellAdecOpenEx` to `cellAdecOpen`** (same 4-argument shape), so the
   audio handle is written and `cellAdecStartSeq` does not see an unwritten
   handle.

If only P0 is done, the movie enters the player with a stub demux and silence:
the screen stays black (or shows the dummy black frame) and the player may
never finish. P0 is still the correct first milestone because it turns the
silent fabricated success into real handles and makes the next gap observable.

### P1 - Deliver the first access unit

1. Replace `cellDmuxSetStream` with a real PAMF pack/PES demux:
   * each 2048-byte sector starts with an MPEG-2 pack `00 00 01 BA`;
   * PES video `00 00 01 E0`, private audio `00 00 01 BD` with substream id;
   * group AVC NALs into one AU per picture; group ATRAC3+ frames after the
     8-byte ATS header;
   * deliver one `CELL_DMUX_ES_MSG_TYPE_AU_FOUND` per AU with PTS/DTS and
     `isRap` from the EP table.
2. Fix `cellDmuxGetAu` to return a guest-resident, big-endian
   `CellDmuxAuInfo` EA (and `auInfoNum`), not `&host_static`.
3. Keep the existing `cellVdec` AU ring; it returns `CELL_VDEC_ERROR_BUSY` when
   the queue is full (`cellVdec.c:425-442`) and the guest retries at
   `0x7FE5B4`.

### P2 - Decode the first real frame

1. Build with `-DPS3RECOMP_FFMPEG_RUNTIME=ON` and a user-supplied LGPL
   libavcodec/libavutil of the matching major version (the runtime loads them
   dynamically; see `ffmpeg_runtime.c`).
2. Verify `cellVdecOpenEx` logs `decoding with libavcodec` and
   `cellVdecGetPicture` returns a decoded 1920x1080 (crop 4) picture.
3. Without P2, the best possible result is a synthetic black 1280x720 PICOUT;
   that is not "the opening movie plays", even if the player advances.

### P3 - Advance/EOS to the menu

1. The demuxer must signal end-of-stream/flush and produce `DEMUX_DONE` /
   `FLUSH_DONE` in the order the player expects; `cellVdecEndSeq` must drain
   the last pictures (the decoder already has an idle drain, `cellVdec.c:176-215`).
2. The native player's finish callback must set `MovieFace.is_finish` and call
   `end_movie`; `MovieRoot.close` then sets `finished=true`, which unblocks
   `display_sequence_gt6` at `0x18DF5`; `boot()` then calls `start_project`
   at `0x1CFEF`.
3. `play_movie` ignores `load`'s return, so a failed load does not
   automatically finish the page. If the movie cannot decode, the skip path
   must be explicit.

### 5.4 Play vs skip

| Goal | Minimum work | Notes |
|---|---|---|
| **Skip the movie** | P0, or the guest profile option | The script's own skip is `skipOpening=1` when `opening_after_autoload` is false or `resume_gp != nil` (`0x18BF3`-`0x18E58`); then `MovieRoot` never opens. At runtime, `MovieRoot.onKeyPress` keysym 65421 -> `end_movie` -> `MovieRoot.close` also skips; the oracle's Enter input at ~54 s is consistent with this path. Skipping needs valid handles for `pause`/`unload`/`close`, but **not** a demuxer or FFmpeg. |
| **Play the movie** | P0 + P1 + P2 (+ P3 for clean EOS) | P0 alone starts the API sequence; P1 makes AUs; P2 makes pixels; P3 makes the player reach `isFinished` without a user skip. |
| **Play, but black** | P0 + P1 | The dummy `cellVdec` path emits black pictures and AUDONE/PICOUT; useful only as a pipeline test, not as the intro. |

Do not claim "intro fixed" for P0/P1; the visible intro requires P2.

---

## 6. Dependencies owned elsewhere (not re-analyzed here)

1. **Boot project load.** `MGOM.start("boot")` only queues
   `manager+0x48=1`/`+0x50="boot"` (`0x568C94`); the consumer that calls the
   project loader `0x5FA338` is not proven to run. Without `boot.adc`
   (`K/LH`), `display_sequence_gt6` and the movie never execute. See
   `docs/analysis/boot-presents-fix.md` sections 0.2-0.5 and 2.3.
2. **Save-data init.** `boot_sequence_common` calls `initSaveData` and sets
   `init_save_data_done`/`sequence_done`. `display_sequence_gt6` parks at
   `0x187C5`/`0x1881F` until both are true. `cellSaveData` behavior is a
   separate workstream.
3. **PFS read-through / PDI cache.** The oracle populates `K/IP.fdupm` and
   truncates `K/IP.fdupi` to `0x14ED5000` before `cellPamf` sees the header.
   The native W2 path currently writes a zero-filled `.fdupi`
   (`docs/analysis/first-visible-ui-check.md` section 2.1). The same PDI
   cache path serves `K/IP`; a zero cache means `cellPamfVerify` sees zeros.
4. **File-worker completion / lwcond.** The movie load is a multi-read sequence
   on a PDI thread. The current `sys_lwcond_wait` is poll-style and the file
   worker can be dropped (`boot-presents-fix.md`, "Opus handoff 2"). Fixing
   this is a prerequisite for reliable large reads, not a codec HLE change.
5. **RSX movie texture path.** `createMovieTexture`/movie draw is separate from
   `cellVdec`. A decoded picture still needs the movie texture bind/upload and
   the draw path; see `docs/analysis/d3d12-draw-readiness.md`.

Also note: `MENUDB` must be initialized and the `OPENING` query must return a
row. If `MENUDB.query1` returns nil, `play_movie` calls `end_movie` and no
native movie path is entered. This is a data/init dependency, not a
`cellPamf` issue.

---

## 7. Unproven claims and corrections to earlier reports

**Unproven / inferred:**

1. **Script `self.load` -> `0x7FDD08` mapping.** The PAMFStream class RTTI,
   method-name table, and function behaviour support the mapping, but no direct
   call/OPD trace from `MovieFace.load` was recovered. The PAMF header call
   sites and setup addresses are proven.
2. **Which layer applies the movie Salsa20.** The oracle proves `cellPamf`
   receives plaintext. It does not prove whether the PDI cache writer or the
   PAMFStream read decrypts. Therefore the `pamf-intro-check.md` path 2
   ("pre-decrypt the file + VFS override bypasses the guest key path") is
   **unproven and potentially a double-decrypt**: the script still calls
   `Tv2.decodeContentsKey`/`setKey`, and if the read path also decrypts, a
   plaintext override is corrupted. Validate this before using the override.
3. **`opening_after_autoload` default.** The script semantics are clear
   (`skipOpening = !opening_after_autoload`), but the fresh-profile default is
   not read here. The oracle plays the intro, so the default is effectively
   "play" for the captured profile.
4. **keysym 65421.** `MovieRoot.onKeyPress` treats `65421` (`0xFF8D`) as the
   end/skip key. The oracle input run's Enter at ~54 s is consistent, but the
   exact pad-to-keysym mapping is not independently verified.
5. **`cellDmuxQueryAttr`/`QueryEsAttr` sizes.** The oracle log does not print
   the attribute contents. The guest allocates from the first attribute word;
   the exact sizes must be measured or taken from a correct PAMF backend. A
   nonzero conservative value is enough for the current stub, not for a real
   demuxer.
6. **Failure behaviour when `load` returns 0.** `play_movie` ignores the
   result; whether the native page still sets `finished` (or stays
   interactive) is not proven. A skip path that relies on `pause`/`unload`
   after a failed load must be tested.
7. **No native run of this path.** The port does not reach the movie today; no
   `cellPamf`/`cellDmux`/`cellVdec`/`cellAdec` line exists in the current
   `work/*.err` logs. The current-build claims above are source/CMake facts,
   not observed runtime results.

**Corrections:**

* `pamf-intro-fix.md` section 5.2 lists 9 missing `cellPamf` + 4 missing
  `cellDmux`; it omits **`cellAdecOpenEx` (0x8B5551A4)**, which GT6 imports and
  calls at `0x800694`.
* `pamf-intro-fix.md` section 5.4 says `cellAdec` has an ATRAC3+ path. It does
  not: `cellAdecDecodeAu` is silence, and `cellAdecAtrac3p.c` is a silence
  stub. The real ATRAC3+ codec in the tree is `cellAtrac` (music).
* `pamf-intro-fix.md` sections 5.1/5.3 describe the HLE's wrong-offset fields
  but do not mention the wrong SDK stream-type constants (`cellPamf.h:31-43`)
  or the 16-byte-vs-32-byte AVC info struct; both must be fixed for
  `GetStreamInfo`.
* `pamf-intro-check.md` section 5.4 says `cellVdec` has a real FFmpeg path
  "when `PS3RECOMP_FFMPEG_RUNTIME` is enabled". The current build has the
  option **OFF** (`CMakeCache.txt:273`), so the real decoder is not in the
  running binary.
* `pamf-intro-fix.md` says the EP iterator functions are needed for
  seeking/metadata. The captured run does not call them; rank them below the
  header/demux start path.

---

## 8. Evidence index

| Evidence | Location |
|---|---|
| boot.adc code/offsets | `work/gt6_vol/projects/gt6/boot/boot.adc`; `work/boot_presents/boot_adc.txt` |
| SHA-256 `boot.adc` / `main.adc` | `7149EF...F10AE` / `5B40B1...A746` (matches `boot-presents-check.md`) |
| `MovieRoot.ad` module | boot.adc `0x20BD1`-`0x21686`; `open` `0x20C3C`, `onInitialize` `0x20D19` |
| `MovieFace` module | boot.adc `0x2104F`-`0x21667`; `play_movie` `0x2106C` |
| Native `MMovieFace` names | EMAIN file `0x1042320`/`0x10423A8`/`0x10424A0` (`load`), `0x1042578` (`setKey`) |
| Native PAMFStream RTTI/vtable | EMAIN file `0x1068410`; vtable vaddr `0x14782B0`; load vaddr `0x7FDD08` |
| PAMFStream setup | EMAIN vaddr `0x7FFA60`; cellDmux/Vdec/Adec call sites in section 2.1 |
| Movie file/keymap | `work/gt6_pfs_keymap.tsv` (`K/IP`); `docs/analysis/pamf-intro-fix.md` sections 1.3/4 |
| Oracle order/args | `work/rpcs3_oracle/rpcs3_input.log:87248-88026`, `109417-109651` |
| Oracle intro/skip | `work/rpcs3_oracle/frames_input/frame_045s.png`; `docs/analysis/rpcs3-oracle.md` section 7.2 |
| PAMF HLE | `third_party/ps3recomp/libs/codec/cellPamf.c` (lines 34-50, 136-185, 362-449, 478-506); `cellPamf.h` |
| Dmux HLE | `third_party/ps3recomp/libs/codec/cellDmux.c` (lines 149-215, 245-259) |
| Vdec HLE | `third_party/ps3recomp/libs/codec/cellVdec.c` (lines 249-267, 392-471, 586-644) |
| FFmpeg option | `third_party/ps3recomp/CMakeLists.txt:191`; `work/build_ps3recomp/CMakeCache.txt:273`; `vdec_ffmpeg.c:225-236` |
| Adec HLE | `third_party/ps3recomp/libs/codec/cellAdec.c` (lines 118-127, 187-197, 228-285); `cellAdecAtrac3p.c:1-7` |
| NID table | `gt6/src/gen/ppu_hle_nids.cpp` lines 1225-1241, 1322-1332, 1734-1747, 2107-2114 |
| Unresolved-NID default | `third_party/ps3recomp/runtime/ppu/ppu_hle.cpp:185-212` |
| Boot/PFS dependency | `docs/analysis/boot-presents-fix.md`; `docs/analysis/first-visible-ui-check.md`; `docs/analysis/CONTINUE-HERE.md` |
