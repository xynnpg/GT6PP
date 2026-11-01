# Build GT6PP with the portable LLVM-MinGW toolchain.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/build-gt6.ps1 [-Clean]
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

$mingw = Get-ChildItem -Path (Join-Path $Root "tools\llvm-mingw") -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "bin\clang.exe" } |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1
if (-not $mingw) {
    throw "LLVM-MinGW not found under tools\llvm-mingw. See docs/BUILDING.md."
}
$mingwBin = Split-Path -Parent $mingw
$env:PATH = "$mingwBin;$env:PATH"
$env:CC = Join-Path $mingwBin "clang.exe"
$env:CXX = Join-Path $mingwBin "clang++.exe"

$generated = Join-Path $Root "gt6\generated\ppu_recomp.h"
$hleTable  = Join-Path $Root "gt6\src\gen\ppu_hle_nids.cpp"
if (-not (Test-Path $generated)) {
    throw "No $generated. Run scripts/relift-gt6.ps1 first (see docs/BUILDING.md)."
}
if (-not (Test-Path $hleTable)) {
    throw "No $hleTable. Run tools/gen_hle_nids.py --all first."
}

$build = Join-Path $Root "gt6\build"
if ($Clean -and (Test-Path $build)) {
    Remove-Item -Recurse -Force $build
}

$sdk = (Resolve-Path (Join-Path $Root "third_party\ps3recomp")).Path -replace '\\','/'
$src = (Resolve-Path (Join-Path $Root "gt6")).Path

python -m cmake -S $src -B $build -G Ninja `
    -DCMAKE_BUILD_TYPE=Release `
    -DGT6_ENABLE_SPU=ON `
    -DPS3RECOMP_DIR="$sdk" `
    -DCMAKE_C_FLAGS="-D_WIN32_WINNT=0x0A00" `
    -DCMAKE_CXX_FLAGS="-D_WIN32_WINNT=0x0A00"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$jobs = if ($env:NUMBER_OF_PROCESSORS) { $env:NUMBER_OF_PROCESSORS } else { 8 }
python -m cmake --build $build -j $jobs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Built: $build\gt6.exe" -ForegroundColor Green
Write-Host "Run:   $build\gt6.exe work\bin\EMAIN.elf"
