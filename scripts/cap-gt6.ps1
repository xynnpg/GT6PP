# One-call render experiment: run GT6 with env overrides, capture a frame, convert to PNG, print pixel stats.
# Usage: powershell -File scripts/cap-gt6.ps1 -Name x1 [] [-Frame 2500] [-Seconds 60]
# Output: work/cap_<Name>/frame_00/{manifest.txt,backbuffer.bmp,backbuffer.png} + stats line (black/blue/white/other %).
param(
    [Parameter(Mandatory)][string]$Name,
    [string]$Env = "",
    [int]$Frame = 2500,
    [int]$Seconds = 60
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Dir = Join-Path $Root "work\cap_$Name"
if (Test-Path $Dir) { Rename-Item $Dir ("$Dir" + "_old_" + (Get-Date -Format HHmmss)) }
New-Item -ItemType Directory -Path $Dir | Out-Null
$env:RSX_CAP = "${Frame}:1"
$env:RSX_CAP_DIR = $Dir
$pairs = @{}; foreach ($p in ($Env -split ",") | Where-Object { $_ }) { $kv = $p -split "=",2; $pairs[$kv[0]] = $kv[1]; Set-Item "Env:$($kv[0])" $kv[1] }
try {
    & (Join-Path $PSScriptRoot "run-gt6.ps1") -Seconds $Seconds -Windowed | Out-Null
} finally {
    foreach ($k in $pairs.Keys) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
    Remove-Item Env:RSX_CAP, Env:RSX_CAP_DIR -ErrorAction SilentlyContinue
}
$bmp = Join-Path $Dir "frame_00\backbuffer.bmp"
if (-not (Test-Path $bmp)) { Write-Host "NO CAPTURE (frame $Frame not reached in ${Seconds}s?)"; exit 1 }
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Bitmap]::FromFile($bmp)
$w = $img.Width; $h = $img.Height
$black = 0; $blue = 0; $white = 0; $other = 0; $n = 0
for ($y = 0; $y -lt $h; $y += 4) { for ($x = 0; $x -lt $w; $x += 4) {
    $c = $img.GetPixel($x, $y); $n++
    if ($c.R -lt 16 -and $c.G -lt 16 -and $c.B -lt 16) { $black++ }
    elseif ($c.R -gt 230 -and $c.G -gt 230 -and $c.B -gt 230) { $white++ }
    elseif ($c.B -gt $c.R + 40 -and $c.B -gt $c.G + 20) { $blue++ }
    else { $other++ }
} }
$img.Save((Join-Path $Dir "frame_00\backbuffer.png"), [System.Drawing.Imaging.ImageFormat]::Png)
$img.Dispose()
$draws = (Select-String -Path (Join-Path $Dir "frame_00\manifest.txt") -Pattern '^\s*op' -ErrorAction SilentlyContinue | Measure-Object).Count
"{0}x{1} black={2:P1} blue={3:P1} white={4:P1} other={5:P1} ops={6}  -> {7}" -f $w,$h,($black/$n),($blue/$n),($white/$n),($other/$n),$draws,(Join-Path $Dir "frame_00\backbuffer.png")
