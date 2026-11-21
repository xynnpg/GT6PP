# Extract GT.VOL with GTToolsSharp and compare scripts/gt6/main.adc with the
# hash GT6PP's docs were written against (US BCUS98296 v1.00).
#
# Run this yourself (a human). GTToolsSharp's repository asks that AI tools do
# not run it; this script is meant to be started by the disc owner.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/extract-gtvol.ps1 -GtVol "D:\PS3_GAME\USRDIR\GT.VOL"
#   (add -Zip <path> to use an already downloaded GTToolsSharp-*-win-x64.zip)
#
# Needs ~16 GB free disk space for the unpacked volume (use -Output to pick the drive).
param(
    [Parameter(Mandatory = $true)][string]$GtVol,
    [string]$Output = "",
    [string]$Zip = "",
    [string]$Version = "5.3.5"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Output) { $Output = Join-Path $Root "work\gt6_vol" }
$ToolDir = Join-Path $Root "tools\GTToolsSharp"
$Log = Join-Path $Root "work\gt6_unpack.log"

# main.adc as documented for the US build (docs/BUILDING.md, pfs-script.md)
$ExpectSha  = "5B40B149E431CE3EB9ADACAC38114208D995BCEBF55FD11C519E8C4BDA00A746"
$ExpectSize = 857518

if (-not (Test-Path $GtVol)) { throw "GT.VOL not found: $GtVol" }
# Files copied off a disc/ISO keep the read-only flag; GTToolsSharp opens the
# volume read/write and fails with UnauthorizedAccessException otherwise.
if ((Get-Item $GtVol).IsReadOnly) { Set-ItemProperty $GtVol -Name IsReadOnly -Value $false }
New-Item -ItemType Directory -Force -Path (Split-Path $Log), $ToolDir | Out-Null

$exe = Get-ChildItem $ToolDir -Recurse -Filter GTToolsSharp.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $exe) {
    if (-not $Zip) {
        $name = "GTToolsSharp-$Version-win-x64.zip"
        $url  = "https://github.com/Nenkai/GTToolsSharp/releases/download/$Version/$name"
        $Zip  = Join-Path $env:TEMP $name
        Write-Host "Downloading $url"
        Invoke-WebRequest -Uri $url -OutFile $Zip
    }
    Write-Host "SHA-256 of zip: $((Get-FileHash $Zip -Algorithm SHA256).Hash)"
    Expand-Archive -Path $Zip -DestinationPath $ToolDir -Force
    $exe = Get-ChildItem $ToolDir -Recurse -Filter GTToolsSharp.exe | Select-Object -First 1
    if (-not $exe) { throw "GTToolsSharp.exe not found after extraction" }
}

# Only compare a main.adc produced by THIS run: a leftover file from an earlier
# extraction must not be able to certify a failed one (GTToolsSharp can exit 0
# after handled errors).
if ((Test-Path $Output) -and (Get-ChildItem $Output -Force | Select-Object -First 1)) {
    throw "Output directory $Output is not empty. Use an empty -Output directory so a stale main.adc cannot be mistaken for this run."
}
Write-Host "Unpacking $GtVol -> $Output (takes a while)"
& $exe.FullName unpack --input $GtVol --output $Output --no-print --log $Log
if ($LASTEXITCODE -ne 0) { throw "GTToolsSharp exited with $LASTEXITCODE (see $Log)" }

$adc = Join-Path $Output "scripts\gt6\main.adc"
if (-not (Test-Path $adc)) {
    Write-Host "main.adc not found at $adc" -ForegroundColor Red
    Write-Host "Look for it with: Get-ChildItem '$Output' -Recurse -Filter main.adc"
    exit 2
}
$item = Get-Item $adc
$hash = (Get-FileHash $adc -Algorithm SHA256).Hash
Write-Host ""
Write-Host "main.adc size  : $($item.Length) (expect $ExpectSize)"
Write-Host "main.adc sha256: $hash"
Write-Host "expected       : $ExpectSha"
if ($hash -eq $ExpectSha -and $item.Length -eq $ExpectSize) {
    Write-Host "RESULT: MATCH - EU GT.VOL main.adc equals the US build." -ForegroundColor Green
    exit 0
}
Write-Host "RESULT: DIFFERENT - report both hashes to the maintainers." -ForegroundColor Yellow
exit 1
