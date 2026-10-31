# Re-run the GT6 analysis + PPU lift pipeline.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/relift-gt6.ps1 [-Jobs 8] [-Chunks 40] [-Functions <path>]
#
# The lift list is not the raw .opd table. It must include the heuristic and
# explicit boundaries that make indirect calls resolvable (see docs/STATUS.md).
# Prefer work/analysis/emain/functions_corrected.json when the boundary audit
# has produced it; otherwise fall back to functions_final3.json.
param(
    [int]$Jobs = 8,
    [int]$Chunks = 40,
    [string]$Functions = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Elf = Join-Path $Root "work\bin\EMAIN.elf"
$Analysis = Join-Path $Root "work\analysis\emain"
$Generated = Join-Path $Root "gt6\generated"
$Sdk = Join-Path $Root "third_party\ps3recomp"
$Gt5p = Join-Path $Root "third_party\GT5P"

if (-not (Test-Path $Elf)) {
    throw "Missing $Elf. Decrypt EMAIN.SELF first (docs/BUILDING.md step 2)."
}
if (-not (Test-Path (Join-Path $Sdk "tools\ppu_lifter.py"))) {
    throw "Missing ps3recomp checkout at $Sdk."
}

New-Item -ItemType Directory -Force -Path $Analysis, $Generated | Out-Null

if (-not $Functions) {
    $corrected = Join-Path $Analysis "functions_corrected.json"
    $Functions = if (Test-Path $corrected) { $corrected }
                 else { Join-Path $Analysis "functions_final3.json" }
}
if (-not (Test-Path $Functions)) { throw "Missing function list $Functions" }
Write-Host "Lift list: $Functions"

Write-Host "[1/4] PPU loader"
python (Join-Path $Sdk "tools\ppu_loader.py") $Elf -o $Analysis
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/4] HLE stub map"
python (Join-Path $Gt5p "scripts\gen_hle_stubs.py") $Elf (Join-Path $Analysis "hle_stubs.json")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/4] PPU lift"
python (Join-Path $Sdk "tools\ppu_lifter.py") $Elf `
    --functions $Functions `
    --hle-stubs (Join-Path $Analysis "hle_stubs.json") `
    --output $Generated `
    --code-end 0xF908C4 `
    --header-name ppu_recomp.h `
    --source-name ppu_recomp.c `
    --chunks $Chunks `
    --jobs $Jobs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/8] setjmp/longjmp call-site patch"
python (Join-Path $Root "tools\setjmp_patch_gt6.py") $Generated
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[5/9] post-lift setjmp guards + boot-script hooks"
python (Join-Path $Root "tools\apply_gt6_post_lift.py") $Generated
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[6/9] .ctors walker r31 preservation"
python (Join-Path $Root "tools\ctor_walk_patch.py") $Generated
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[7/9] post-lift verification"
python (Join-Path $Root "tools\post_lift_fixes.py") $Generated
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[8/9] WWS job-manager PM (SPU image id 5)"
powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\lift-spu-gt6.ps1") -Force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[9/9] HLE NID table"
python (Join-Path $Sdk "tools\gen_hle_nids.py") --all --out (Join-Path $Root "gt6\src\gen\ppu_hle_nids.cpp")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Lift complete. Build with: powershell -File scripts/build-gt6.ps1" -ForegroundColor Green
