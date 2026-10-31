# Run the GT6 port for a bounded time and capture the log.
# Usage: powershell -File scripts/run-gt6.ps1 [-Seconds 20] [-Windowed]
param(
    [int]$Seconds = 20,
    [switch]$Windowed
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Exe = Join-Path $Root "gt6\build\gt6.exe"
$Elf = Join-Path $Root "work\bin\EMAIN.elf"
$Log = Join-Path $Root "work\gt6_run.log"

# The MinGW build links the LLVM-MinGW runtime DLLs dynamically.
$mingw = Get-ChildItem -Path (Join-Path $Root "tools\llvm-mingw") -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "bin\clang.exe" } |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1
if ($mingw) { $env:PATH = "$(Split-Path -Parent $mingw);$env:PATH" }

if (-not (Test-Path $Exe)) { throw "Missing $Exe. Build first." }
if (-not (Test-Path $Elf)) { throw "Missing $Elf. Decrypt EMAIN.SELF first." }

if ($Windowed) {
    Remove-Item Env:PS3_HEADLESS -ErrorAction SilentlyContinue
} else {
    $env:PS3_HEADLESS = "1"
}
if (-not $env:PS3_VERBOSE) { $env:PS3_VERBOSE = "0" }

Write-Host "Running $Exe for ${Seconds}s (headless=$(-not $Windowed))..."
$p = Start-Process -FilePath $Exe -ArgumentList @($Elf) -WorkingDirectory $Root `
    -NoNewWindow -PassThru `
    -RedirectStandardOutput $Log -RedirectStandardError "$Log.err"

if (-not $p.WaitForExit($Seconds * 1000)) {
    Write-Host "Still running after ${Seconds}s; stopping."
    try { $p.Kill() } catch {}
    Start-Sleep -Milliseconds 300
}

Write-Host ""
Write-Host "--- stdout tail ---"
if (Test-Path $Log) { Get-Content $Log -Tail 80 }
Write-Host ""
Write-Host "--- stderr tail ---"
if (Test-Path "$Log.err") { Get-Content "$Log.err" -Tail 120 }
Write-Host ""
Write-Host "Full logs: $Log / $Log.err"
