# Reproducibility gaps found while setting up from a clean clone

Findings from an independent setup attempt on Windows 11 with an EU disc
(`BCES01893`). None of these were fixed upstream behaviour; they are requests.

1. **`third_party/ps3recomp` base is unpinned.** BUILDING.md says `master`, but
   `patches/*.patch` only apply onto an unrecorded commit. Please record the
   exact base commit hash (or publish the patched tree as a fork/branch).
2. **Patch order is implicit.** `ps3recomp-mingw-seh` overlaps the `cellFs.c`
   change in `ps3recomp-gt6-runtime`. Document the apply order.
3. **`ps3recomp-gt6-bringup-dds.patch` has a hunk header whose line counts do
   not match its body**, so `git apply` rejects it (`git apply --recount`
   is needed).
4. **Line endings.** The patches are LF in the repo, but with Windows
   `core.autocrlf=true` they are checked out as CRLF and fail to apply.
   `.gitattributes` (added in this change) marks `*.patch` as `-text`.
5. **Function lists are not committed.** `relift-gt6.ps1` prefers
   `work/analysis/emain/functions_corrected.json`, which only exists locally.
   Without it, `functions_final3.json` (also local) is the fallback; neither can
   be regenerated from a clean clone. Please commit them (they contain no
   copyrighted data) or document how to produce them.
6. **No recorded hash of the US `EMAIN.elf`.** Adding SHA-256 values to
   BUILDING.md lets owners verify their decrypt step.

Region check for the EU disc: see `eu-bces01893-compat.md`.
