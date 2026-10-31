# Build and run the D3D12 rsx_backend self-test outside the emulator.
#
#   pwsh -File tools/patches/run_rsx_d3d12_selftest.ps1
#   pwsh -File tools/patches/run_rsx_d3d12_selftest.ps1 -NoVP
#
# Exit code 0 means both subtests passed. The legacy subtest uses the built-in
# fixed-function pipeline; the VP subtest compiles a hand-assembled NV40 vertex
# program through rsx_vp_decompiler -> D3DCompile -> CreateGraphicsPipelineState.
param(
    [switch]$NoVP
)

$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$video = Join-Path $root 'third_party\ps3recomp\libs\video'
$inc   = Join-Path $root 'third_party\ps3recomp\include'
$sys   = Join-Path $root 'third_party\ps3recomp\libs\system'
$misc  = Join-Path $root 'third_party\ps3recomp\libs\misc'

$clang = Join-Path $root 'tools\llvm-mingw\llvm-mingw-20261020-ucrt-x86_64\bin\clang.exe'
if (-not (Test-Path $clang)) {
    $cmd = Get-Command clang -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "clang not found (expected $clang)" }
    $clang = $cmd.Source
}

$outDir = Join-Path $env:TEMP 'gt6pp_rsx_d3d12_selftest'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$exe = Join-Path $outDir 'rsx_d3d12_selftest.exe'

$sources = @(
    (Join-Path $PSScriptRoot 'rsx_d3d12_selftest_host.c'),
    (Join-Path $video 'rsx_d3d12_backend.c'),
    (Join-Path $video 'rsx_commands.c'),
    (Join-Path $video 'rsx_vp_decompiler.c'),
    (Join-Path $video 'rsx_fp_decompiler.c'),
    (Join-Path $video 'rsx_texture_layout.c'),
    (Join-Path $video 'rsx_vertex_fetch.c')
)

& $clang -std=gnu17 -O1 -g -D_WIN32_WINNT=0x0A00 `
    "-I$inc" "-I$sys" "-I$video" "-I$misc" `
    @sources `
    -ld3d12 -ldxgi -ld3dcompiler -lgdi32 -luser32 -lole32 `
    -o $exe
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$runArgs = @()
if ($NoVP) { $runArgs += '--no-vp' }
& $exe @runArgs
exit $LASTEXITCODE
