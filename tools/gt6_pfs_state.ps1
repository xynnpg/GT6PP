<#
.SYNOPSIS
  Read-only snapshot of the GT6 PDIPFS boot-script cache state.

.DESCRIPTION
  Prints size, first bytes and SHA-256 for the decrypted boot script and the
  generated PDIPFS cache files, parses the PD.fdupm header, and compares the
  cache head with the raw GT.VOL entry at 0xA6F000. It never launches gt6.exe
  and never writes to game data.

  Run from anywhere:
    powershell -ExecutionPolicy Bypass -File tools\gt6_pfs_state.ps1
#>
[CmdletBinding()]
param(
    [string]$Root = ''
)

$ErrorActionPreference = 'Stop'
if (-not $Root) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $Root = Split-Path -Parent $here
}
function Show-File([string]$Label, [string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host ("{0,-28} MISSING  {1}" -f $Label, $Path)
        return $null
    }
    $f = Get-Item -LiteralPath $Path
    $fs = [IO.File]::OpenRead($Path)
    try {
        $n = [Math]::Min(16, $f.Length)
        $head = New-Object byte[] $n
        [void]$fs.Read($head, 0, $n)
    } finally { $fs.Dispose() }
    $hex = ($head | ForEach-Object { $_.ToString('X2') }) -join ' '
    $sha = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    Write-Host ("{0,-28} {1,10}  {2}" -f $Label, $f.Length, $Path)
    Write-Host ("{0,-28} head: {1}" -f '', $hex)
    Write-Host ("{0,-28} sha256: {1}" -f '', $sha)
    return $f
}

Write-Host "=== GT6 PDIPFS boot-script state ==="
Write-Host "root: $Root"
Write-Host ""

$dec = Join-Path $Root 'work\gt6_vol\scripts\gt6\main.adc'
Show-File 'decrypted main.adc' $dec | Out-Null

$hdd = Join-Path $Root 'work\gt6_hdd0\game\BCUS98296\USRDIR\PDIPFS\K'
$disc = Join-Path $Root 'PS3-Version\Gran Turismo 6 (USA) (En,Ja,Fr)\game\BCUS98296\USRDIR\PDIPFS\K'
$extracted = Join-Path $Root 'PS3-Version\Gran Turismo 6 (USA) (En,Ja,Fr)\PS3_GAME\USRDIR\GT_extracted\scripts\gt6\main.adc'

foreach ($pair in @(
    @('hdd PD.fdupi',  (Join-Path $hdd 'PD.fdupi')),
    @('hdd PD.fdupm',  (Join-Path $hdd 'PD.fdupm')),
    @('hdd K/4D',      (Join-Path $hdd '4D')),
    @('disc PD.fdupi', (Join-Path $disc 'PD.fdupi')),
    @('disc PD.fdupm', (Join-Path $disc 'PD.fdupm')),
    @('GT_extracted',  $extracted)
)) { Show-File $pair[0] $pair[1] | Out-Null }

$fdupm = Join-Path $hdd 'PD.fdupm'
if (Test-Path -LiteralPath $fdupm) {
    $b = [IO.File]::ReadAllBytes($fdupm)
    $nz = 0
    for ($i = 8; $i -lt $b.Length; $i++) { if ($b[$i] -ne 0) { $nz++ } }
    $u32_0 = ([int]$b[0] -shl 24) -bor ([int]$b[1] -shl 16) -bor ([int]$b[2] -shl 8) -bor [int]$b[3]
    $u32_4 = ([int]$b[4] -shl 24) -bor ([int]$b[5] -shl 16) -bor ([int]$b[6] -shl 8) -bor [int]$b[7]
    Write-Host ""
    Write-Host ("PD.fdupm: bytes={0} header0=0x{1:X8} header4=0x{2:X8} (ZSize?) nonzero_after_8={3}" -f $b.Length, $u32_0, $u32_4, $nz)
}

$vol = Join-Path $Root 'PS3-Version\Gran Turismo 6 (USA) (En,Ja,Fr)\PS3_GAME\USRDIR\GT.VOL'
$fdupi = Join-Path $hdd 'PD.fdupi'
if ((Test-Path -LiteralPath $vol) -and (Test-Path -LiteralPath $fdupi)) {
    $cmp = [Math]::Min((Get-Item -LiteralPath $fdupi).Length, 0x3E000)
    $a = New-Object byte[] $cmp
    $b = New-Object byte[] $cmp
    $fv = [IO.File]::OpenRead($vol); $ff = [IO.File]::OpenRead($fdupi)
    try {
        [void]$fv.Seek(0xA6F000, [IO.SeekOrigin]::Begin)
        [void]$fv.Read($a, 0, $cmp)
        [void]$ff.Read($b, 0, $cmp)
    } finally { $fv.Dispose(); $ff.Dispose() }
    $same = $true; $first = -1
    for ($i = 0; $i -lt $cmp; $i++) { if ($a[$i] -ne $b[$i]) { $same = $false; $first = $i; break } }
    Write-Host ("PD.fdupi vs GT.VOL@0xA6F000 first 0x{0:X}: identical={1} first_diff={2}" -f $cmp, $same, $first)
}

Write-Host ""
Write-Host "Expected decrypted head: 41 44 43 48 30 31 32 00 (ADCH012\0), size 857518"
Write-Host "Expected raw entry head: 25 0F FF FE 9B 46 77 B1, ZSize 0x3EE28"
Write-Host "Expected PS2ZIP head after cipher: C5 EE F7 FF (little-endian magic 0xFFF7EEC5)"
