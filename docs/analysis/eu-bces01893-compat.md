# EU disc (BCES01893) vs the US-based address lists

**Question:** GT6PP is documented against the US disc `BCUS98296` v1.00. Do the
hard-coded guest addresses, function lists and post-lift patches also apply to
the EU disc `BCES01893`?

**Short answer:** everything checked so far is consistent with compatibility.
`EMAIN.elf` layout matches, the raw `GT.VOL` slices hash identically, and the
extracted `scripts/gt6/main.adc` is byte-identical to the documented US file.
These are sampled checks, not a check of every address the function lists and
patches use; a relift and a build on the EU ELF are needed to confirm it.

## Disc facts (EU, from a user-owned dump)

| Item | Value |
|---|---|
| Title ID | `BCES01893` (from `PARAM.SFO`) |
| `APP_VER` | `01.00` |
| `PS3_SYSTEM_VER` | `04.5000` |
| ISO size | identical to the US dump |
| `USRDIR/EBOOT.BIN` | 72,920 bytes (encrypted SELF, `SCE\0`) |
| `USRDIR/EMAIN.SELF` | 8,843,160 bytes (encrypted SELF, `SCE\0`) |
| `USRDIR/GT.VOL` | 15,407,310,848 bytes (same size as the US file) |
| `PS3_UPDATE/PS3UPDAT.PUP` | 268,435,456 bytes |

## Decrypted ELFs (RPCS3 `--decrypt`, per BUILDING.md section 2)

| File | Size | SHA-256 |
|---|---|---|
| `EBOOT.elf` | 143,064 | `C7BD80B00F3DEBC16E5B49F1212409802472FE2F58FF5AD52BAA25691454129C` |
| `EMAIN.elf` | 22,371,400 | `ACB00C19259F10EE5F802B23734C53CDF1E1AAEB5DB5C8FC58CA140AD7A47A9B` |

Both sizes equal the figures in BUILDING.md for the US build.

## Layout checks (`python tools/gt6_region_check.py`)

`ppu_loader.py` output on the EU ELF equals the documented US numbers:
entry OPD `0x148E2E0` -> code `0x10230`, TOC `0x14ED560`, 44,626 OPD
descriptors, 33,091 unique functions, 747 imports / 46 libraries, same two
load segments.

`tools/gt6_region_check.py` additionally decodes the first instruction at ten
addresses the docs and patches depend on. All match: `0x13830` (script loader
prologue), `0x987910` (`bctr` of the ADCH jump table), `0x9CD410`, `0x9FF530`,
`0xA43AB4`, `0xA564EC`, `0xA569D0`, `0xB98168`/`0xB9828C` (setjmp/longjmp) and
`0xF9AC18` (HLE import stub pattern).

## GT.VOL raw slices

The two raw `GT.VOL` slices whose SHA-256 values are already recorded in the
repo docs (`boot-presents-check.md`, `pfs-wo-check.md`, `pfs-script.md`) hash
identically on the EU file. Together with the identical file size this makes
EU and US `GT.VOL` very likely byte-identical or near-identical.

## GT.VOL extraction (run by the disc owner with GTToolsSharp 5.3.5)

`scripts/extract-gtvol.ps1` unpacked the EU `GT.VOL` (PFS serial `405868366`,
title `GT6-PISCINAS-323419048`, 4207 TOC entries, 32,591 files extracted).
`scripts/gt6/main.adc` is **857,518 bytes, SHA-256 `5B40B149...A746`: identical
to the US value** recorded in the docs.

## What this does not prove

- No US `EMAIN.elf` hash is recorded in the repo, so byte-identity with the US
  ELF is **not** confirmed, only that the layout the port relies on matches.
  A US owner can compare their `EMAIN.elf` SHA-256 with the value above.
- Only `main.adc` was compared at file level; the other ~32,590 files were not
  hashed against US values (no US file list is recorded in the repo).
  GTToolsSharp's repository forbids AI/LLM use, so the extraction was run by
  the human disc owner, not by the AI.
- Nothing was lifted, built or run. This only covers static checks.

## Suggested next steps for someone with the EU disc

1. `python tools/gt6_region_check.py work/bin/EMAIN.elf` - expect PASS.
2. `powershell -ExecutionPolicy Bypass -File scripts/extract-gtvol.ps1 -GtVol <path>\GT.VOL`
   and compare the printed `main.adc` hash.
3. If both agree, the existing relift and boot-script override should work
   unchanged for EU; run the normal build and report the first divergence.
