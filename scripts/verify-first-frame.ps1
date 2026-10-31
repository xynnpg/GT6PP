# Build-agnostic first-frame verification for GT6PP.
#
# Seeds the boot/presents PFS keys from the user's GT.VOL, runs the native port
# with its own backbuffer capture (no desktop screenshots), then reports whether
# any captured frame contains visible pixels.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\verify-first-frame.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\verify-first-frame.ps1 -Seconds 420 -Seed
#
# Run from the repository root. The script never edits game data; it copies raw
# GT.VOL slices into the ignored work/ HDD tree.

param(
    [int]$Seconds = 300,
    [switch]$Seed,
    [string]$CaptureDir = "work/rsxcap_verify",
    [string]$Log = "work/verify_run.err"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Get-Process | Where-Object { $_.ProcessName -like "*gt6*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

if ($Seed) {
    python tools\gt6_seed_pfs_cache.py --boot-set
    if ($LASTEXITCODE -ne 0) { throw "PFS cache seeding failed" }
}

Remove-Item $CaptureDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $CaptureDir | Out-Null

$env:PPU_STUCKMAX = "1000000"
$env:RSX_CAP = "1:8:60"
$env:RSX_CAP_DIR = $CaptureDir
Remove-Item Env:PS3_HEADLESS,Env:GCM_DRAWPROBE,Env:GCM_GUEST_FB,Env:GT6_CONSOLE -ErrorAction SilentlyContinue

$exe = Join-Path $root "gt6\build\gt6.exe"
if (-not (Test-Path $exe)) { throw "missing $exe (build first)" }

$p = Start-Process -FilePath $exe -ArgumentList @("work\bin\EMAIN.elf") `
    -WorkingDirectory $root -RedirectStandardOutput "work\verify_run.log" `
    -RedirectStandardError $Log -PassThru

Write-Host "running $exe for $Seconds s (capture: $CaptureDir)"
Start-Sleep -Seconds $Seconds
$p.Refresh()
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }

$patterns = [ordered]@{
    "boot.adc (K/LH)"      = "K/LH|boot\.adc"
    "boot.mproject (K/KG)" = "K/KG|boot\.mproject"
    "BootProject (K/IE)"   = "K/IE|BootProject"
    "PresentsRoot (K/WD)"  = "K/WD|PresentsRoot"
    "fonts"                = "K/(4M|5I|V4|HP|TY|G4|CP|6L|9N|D8|MR|2F)"
    "PFS overrides"        = "pfs override"
    "immediate draws"      = "\[RSX\] IMMEDIATE"
    "textured draws"       = "textured=1|tex0=0x[1-9A-Fa-f]"
    "crash"                = "ACCESS VIOLATION"
}
Write-Host "`n[log summary]"
foreach ($name in $patterns.Keys) {
    $count = (Select-String -Path $Log -Pattern $patterns[$name] -ErrorAction SilentlyContinue | Measure-Object).Count
    Write-Host ("  {0,-22} {1}" -f $name, $count)
}

$bmp = Get-ChildItem $CaptureDir -Recurse -Filter backbuffer.bmp -ErrorAction SilentlyContinue
if (-not $bmp) {
    Write-Host "`nNo backbuffer.bmp captured. The run may not have presented a display frame."
    exit 1
}

Write-Host "`n[frame check]"
python tools\gt6_frame_check.py $CaptureDir --glob "frame_*/backbuffer.bmp" --min-nonblack 5
exit $LASTEXITCODE
