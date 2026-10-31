# Lift every captured raw SPURS job binary and regenerate the job registry.
#
# GT6's job chains hand a raw code+data image to spu_workload_dispatch_job()
# (libs/spurs/cellSpurs.c, jc_run_one_job). That path calls spurs_job.c, which
# stages the binary at LS 0:
#
#     spu_run_spurs_job(): "binary at LS 0 (PIC, so delta 0 keeps the lifted
#     addresses)" -- memcpy(ls, vm_base + ea_bin, size_bin)
#
# so every job image is lifted with --base 0. The runtime fingerprints exactly
# the bytes it dispatches, and the SPU_DUMP_MISS filename carries that value, so
# spujob_<FP>_<size>.bin is both the input and the registry key.
#
# Image ids: 1..4 are the four embedded SPU ELFs (spu_workloads.c), 5 is the WWS
# job-manager policy module (spu_workloads_pm.c), and jobs take 6..N in sorted
# fingerprint order. The script owns gt6/generated/spu_lifted/jobs/ and
# gt6/src/gen/spu_workloads_jobs.c, so re-running it never loses the registry.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/lift-spu-jobs.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/lift-spu-jobs.ps1 `
#       -DumpDir work/spu_jobs/dump
param(
    [string]$DumpDir = "",
    [int]$FirstImageId = 6
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $DumpDir) { $DumpDir = Join-Path $Root "work\spu_jobs\dump" }
if (-not (Test-Path $DumpDir)) { throw "Missing dump dir $DumpDir" }

$Sdk = Join-Path $Root "third_party\ps3recomp"
$Work = Join-Path $Root "work\spu_jobs\analysis"
$JobsDir = Join-Path $Root "gt6\generated\spu_lifted\jobs"
$Registry = Join-Path $Root "gt6\src\gen\spu_workloads_jobs.c"
$FindTool = Join-Path $Sdk "tools\find_spu_functions.py"
$LiftTool = Join-Path $Sdk "tools\spu_lifter.py"

foreach ($p in @($FindTool, $LiftTool)) {
    if (-not (Test-Path $p)) { throw "Missing tool $p" }
}

$nameRe = '^spujob_([0-9A-Fa-f]{16})_(\d+)\.bin$'
$dumps = @(Get-ChildItem -Path $DumpDir -Filter "spujob_*.bin" | Sort-Object Name)
if ($dumps.Count -eq 0) { throw "No spujob_*.bin files in $DumpDir" }

# Optional per-image code/data cutoff (LS offset of the first known data word).
# Empty by default: the whole image is lifted. If a run halts in
# spu_unsupported() inside an image's data tail, add its fingerprint here (e.g.
# 'CB9BD0241BB0DE67' = 0x08D90) rather than hand-editing generated C; re-running
# this script then reproduces the trimmed lift and the same registry.
$CodeEndByFp = @{
}

# Rebuild the generated tree from scratch: this directory is script-owned and a
# stale image left behind would still be compiled by the CMake glob.
if (Test-Path $JobsDir) { Remove-Item -Recurse -Force $JobsDir }
New-Item -ItemType Directory -Force -Path $JobsDir, $Work | Out-Null

$jobs = @()
$index = 0

foreach ($dump in $dumps) {
    if ($dump.Name -notmatch $nameRe) {
        Write-Warning "skipping unexpected name $($dump.Name)"
        continue
    }
    $fp = $Matches[1].ToUpperInvariant()
    $size = [int]$Matches[2]
    $shortFp = $fp.Substring(0, 8).ToLowerInvariant()
    $prefix = "job_${shortFp}_"
    $imageId = $FirstImageId + $index

    # The runtime's fingerprint is FNV-1a-64 with 1469598103934665603 (the
    # offset basis with a digit dropped), not the standard basis. Verify the
    # filename against the bytes so a stale/renamed dump cannot be registered.
    $check = & python -c @'
import sys
from pathlib import Path
b = Path(sys.argv[1]).read_bytes()
h = 1469598103934665603
for x in b:
    h = ((h ^ x) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
print(len(b))
print(format(h, '016X'))
'@ $dump.FullName
    if ($LASTEXITCODE -ne 0) { throw "fingerprint check failed for $($dump.Name)" }
    $actualSize = [int]$check[0]
    $actualFp = ([string]$check[1]).ToUpperInvariant()
    if ($actualSize -ne $size) { throw "$($dump.Name): filename size $size != $actualSize bytes" }
    if ($actualFp -ne $fp) { throw "$($dump.Name): filename fp $fp != runtime fp $actualFp" }

    $imgWork = Join-Path $Work $fp
    New-Item -ItemType Directory -Force -Path $imgWork | Out-Null
    $funcsJson = Join-Path $imgWork "functions.json"
    $codeBin = Join-Path $imgWork "code.bin"
    $outDir = Join-Path $JobsDir $fp

    Write-Host ("[{0}/{1}] {2} ({3} bytes, fp 0x{4}, image {5})" -f `
        ($index + 1), $dumps.Count, $dump.Name, $size, $fp, $imageId)

    & python $FindTool $dump.FullName --raw --base 0 `
        --code-out $codeBin --out $funcsJson 2>&1 |
        Tee-Object -FilePath (Join-Path $imgWork "find.log")
    if ($LASTEXITCODE -ne 0) { throw "find_spu_functions failed for $($dump.Name)" }

    $liftArgs = @(
        $codeBin, "--base", "0", "--functions", $funcsJson,
        "--symbol-prefix", $prefix, "--output", $outDir,
        "--source-name", "spu_recomp.c", "--header-name", "spu_recomp.h"
    )
    $codeEnd = $CodeEndByFp[$fp]
    if ($null -ne $codeEnd) {
        $liftArgs += @("--code-end", ("0x{0:X}" -f [int64]$codeEnd))
    }
    & python $LiftTool @liftArgs 2>&1 |
        Tee-Object -FilePath (Join-Path $imgWork "lift.log")
    if ($LASTEXITCODE -ne 0) { throw "spu_lifter failed for $($dump.Name)" }

    $funcCount = (Get-Content $funcsJson -Raw | ConvertFrom-Json).Count
    $entry = Join-Path $outDir "spu_recomp.c"
    if (-not (Select-String -Path $entry -Pattern "void ${prefix}spu_func_00000000\(" -Quiet)) {
        throw "$($dump.Name): lift has no entry function at LS 0"
    }

    $jobs += [pscustomobject]@{
        Fp        = $fp
        Size      = $size
        Id        = $imageId
        Short     = $shortFp
        Prefix    = $prefix
        FuncCount = $funcCount
    }
    $index++
}

if ($jobs.Count -eq 0) { throw "No valid spujob images processed" }

# ---- registry ---------------------------------------------------------------
# Exact content is mirrored in docs/analysis/spu-jobs.md. Keep this generator
# authoritative: do not hand-edit gt6/src/gen/spu_workloads_jobs.c.
$sb = [System.Text.StringBuilder]::new()
[void]$sb.AppendLine("/* Raw SPURS job binaries GT6 dispatches through its job chains (image ids")
[void]$sb.AppendLine(" * $($jobs[0].Id)..$($jobs[-1].Id)).")
[void]$sb.AppendLine(" * GENERATED by scripts/lift-spu-jobs.ps1; do not edit by hand.")
[void]$sb.AppendLine(" *")
[void]$sb.AppendLine(" * The runtime fingerprints exactly the bytes cellSpurs hands to")
[void]$sb.AppendLine(" * spu_workload_dispatch_job(), so each key is the FNV-1a-64 value the")
[void]$sb.AppendLine(" * runtime computes (basis 1469598103934665603) over")
[void]$sb.AppendLine(" * work/spu_jobs/dump/spujob_<FP>_<size>.bin.")
[void]$sb.AppendLine(" *")
[void]$sb.AppendLine(" * Lifted at LS base 0: runtime/spu/spurs_job.c stages a job binary at LS 0")
[void]$sb.AppendLine(" * and enters the lifted function for address 0. Image id 5 is the WWS")
[void]$sb.AppendLine(" * job-manager PM (spu_workloads_pm.c); ids 1..4 are embedded SPU ELFs. */")
[void]$sb.AppendLine('#include "spu_workload.h"')
[void]$sb.AppendLine("")
[void]$sb.AppendLine("extern void spu_begin_image(int image_id);")
foreach ($j in $jobs) {
    [void]$sb.AppendLine("extern void $($j.Prefix)spu_func_00000000(spu_context*);")
}
foreach ($j in $jobs) {
    [void]$sb.AppendLine("extern void $($j.Prefix)spu_recomp_register(void);")
}
[void]$sb.AppendLine("")
[void]$sb.AppendLine("void gt6_spu_register_jobs(void)")
[void]$sb.AppendLine("{")
foreach ($j in $jobs) {
    [void]$sb.AppendLine("    /* $($j.Fp), $($j.Size) bytes, $($j.FuncCount) lifted functions */")
    [void]$sb.AppendLine("    spu_begin_image($($j.Id));")
    [void]$sb.AppendLine("    $($j.Prefix)spu_recomp_register();")
    [void]$sb.AppendLine("    spu_workload_register_img(0x$($j.Fp)ULL,")
    [void]$sb.AppendLine("                              $($j.Prefix)spu_func_00000000,")
    [void]$sb.AppendLine("                              $($j.Id), `"spujob_$($j.Fp)`");")
}
[void]$sb.AppendLine("    spu_begin_image(0);")
[void]$sb.AppendLine("}")
Set-Content -Path $Registry -Value $sb.ToString() -Encoding ASCII

$total = ($jobs | Measure-Object -Property FuncCount -Sum).Sum
Write-Host ""
Write-Host "Lifted $($jobs.Count) job image(s), $total functions" -ForegroundColor Green
Write-Host "Sources:  $JobsDir" -ForegroundColor Green
Write-Host "Registry: $Registry" -ForegroundColor Green
