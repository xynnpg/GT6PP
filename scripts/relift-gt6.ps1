# Re-run the GT6 analysis + PPU lift pipeline.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/relift-gt6.ps1 [-Jobs 8] [-Chunks 32]
param(
    [int]$Jobs = 8,
    [int]$Chunks = 32
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

Write-Host "[1/4] PPU loader"
python (Join-Path $Sdk "tools\ppu_loader.py") $Elf -o $Analysis
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[2/4] filter OPD list to executable addresses"
python -c "import json; f=json.load(open(r'$($Analysis -replace '\\','/')/EMAIN.functions.json')); g=[x for x in f if int(x['start'],16)<0xF908C4]; json.dump(g,open(r'$($Analysis -replace '\\','/')/functions_code.json','w'),indent=1); print(len(f),'->',len(g))"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[3/4] HLE stub map + PPU lift"
python (Join-Path $Gt5p "scripts\gen_hle_stubs.py") $Elf (Join-Path $Analysis "hle_stubs.json")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python (Join-Path $Sdk "tools\ppu_lifter.py") $Elf `
    --functions (Join-Path $Analysis "functions_code.json") `
    --hle-stubs (Join-Path $Analysis "hle_stubs.json") `
    --output $Generated `
    --code-end 0xF908C4 `
    --header-name ppu_recomp.h `
    --source-name ppu_recomp.c `
    --chunks $Chunks `
    --jobs $Jobs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[4/4] HLE NID table"
python (Join-Path $Sdk "tools\gen_hle_nids.py") --all --out (Join-Path $Root "gt6\src\gen\ppu_hle_nids.cpp")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Lift complete. Build with: powershell -File scripts/build-gt6.ps1" -ForegroundColor Green
