# Verify a REAL GT6 frame (diagnostic overlay disabled).
#
# Runs the native port one or more times with GT6_BRINGUP_DDS=0, captures the
# backend's own backbuffer, and reports whether the game itself produced a
# non-black frame. The diagnostic DDS overlay is explicitly disabled so it
# cannot fake a PASS.
#
# Usage (from the repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\verify-real-frame.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\verify-real-frame.ps1 -Trials 3 -Seconds 150 -Build
#
# Exit code 0 if any trial produced a real PASS, 1 otherwise.

param(
    [int]$Trials = 2,
    [int]$Seconds = 180,
    [switch]$Build,
    [string]$LogPrefix = "work/real_verify"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Get-Process | Where-Object { $_.ProcessName -like "*gt6*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

if ($Build) {
    powershell -ExecutionPolicy Bypass -File scripts\build-gt6.ps1
    if ($LASTEXITCODE -ne 0) { throw "build failed" }
}

$exe = Join-Path $root "gt6\build\gt6.exe"
if (-not (Test-Path $exe)) { throw "missing $exe" }

$anyPass = $false
for ($trial = 1; $trial -le $Trials; $trial++) {
    $err = "$LogPrefix`_$trial.err"
    $out = "$LogPrefix`_$trial.out"
    $cap = "work/rsxcap_real_verify_$trial"
    Remove-Item $cap -Recurse -Force -ErrorAction SilentlyContinue

    $env:GT6_BRINGUP_DDS = "0"          # must stay off for a real result
    $env:GT6_BOOTUI_TRACE = "1"
    $env:GT6_BOOT_TRACE = "1"
    $env:PS3_LWCOND_TRACE = "1"
    $env:PS3_VERBOSE = "1"
    $env:PPU_STUCKMAX = "1000000"
    $env:RSX_CAP = "1:4:60"
    $env:RSX_CAP_DIR = $cap
    Remove-Item Env:PS3_HEADLESS,Env:PS3_LWCOND_POLL,Env:GCM_DRAWPROBE,Env:GCM_GUEST_FB -ErrorAction SilentlyContinue

    Write-Host "`n=== trial $trial / $Trials ==="
    $p = Start-Process -FilePath $exe -ArgumentList @("work\bin\EMAIN.elf") `
        -WorkingDirectory $root -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    Start-Sleep -Seconds $Seconds
    $p.Refresh()
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }

    $counts = [ordered]@{
        "MenuClassDefine" = "MenuClassDefine"
        "boot keys"       = "K/LH|K/KG|K/IE|K/WD"
        "MGOM.start"      = "MGOM\.start"
        "project load"    = "project load"
        "immediate draws" = "\[RSX\] IMMEDIATE"
        "drawdiag"        = "\[DRAWDIAG\]"
        "fast-wake"       = "fast-wake"
        "LWCOND waits"    = "\[LWCOND\] wait"
        "LWCOND wakes"    = "\[LWCOND\] woke"
        "crash"           = "ACCESS VIOLATION"
    }
    foreach ($name in $counts.Keys) {
        $n = (Select-String -Path $err -Pattern $counts[$name] -ErrorAction SilentlyContinue | Measure-Object).Count
        Write-Host ("  {0,-18} {1}" -f $name, $n)
    }

    $bmp = Get-ChildItem $cap -Recurse -Filter backbuffer.bmp -ErrorAction SilentlyContinue
    if ($bmp) {
        # scei is ~1.5-3.3% screen coverage; 5% would reject a real legal image.
        python tools\gt6_frame_check.py $cap --glob "frame_*/backbuffer.bmp" --min-nonblack 1
        $framePass = ($LASTEXITCODE -eq 0)

        # A side-effect image (overlay/cover) can be non-black. Require a real
        # GPB texture bind in the backend manifest: t0 != 0 or DXT1 fmt 0xA6.
        $manifest = Get-ChildItem $cap -Recurse -Filter manifest.txt -ErrorAction SilentlyContinue | Select-Object -First 1
        $realDraw = $false
        if ($manifest) {
            $m = Get-Content $manifest.FullName -Raw
            if ($m -match "t0=0x(?!0{8})" -or $m -match "fmt=0xA6") { $realDraw = $true }
            Write-Host "  manifest: $($manifest.FullName) real-texture-draw=$realDraw"
        } else {
            Write-Host "  manifest: missing"
        }
        if ($framePass -and $realDraw) { $anyPass = $true }
        elseif ($framePass) { Write-Host "  frame is non-black but has no real GPB texture draw" }
    } else {
        Write-Host "  no backbuffer.bmp captured"
    }
}

if ($anyPass) {
    Write-Host "`nREAL FRAME PASS"
    exit 0
}
Write-Host "`nNo real non-black game frame."
exit 1
