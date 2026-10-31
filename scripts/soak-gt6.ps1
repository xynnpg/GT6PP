# Boot GT6PP several times headless and report the milestones that matter until
# the frame loop exists. This is the port's progress measure: the boot currently
# stops at the init-chain flag, so a run-to-run spread is itself a finding.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts/soak-gt6.ps1 [-Runs 8] [-Seconds 30]
param(
    [int]$Runs = 8,
    [int]$Seconds = 30
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Exe = Join-Path $Root "gt6\build\gt6.exe"
$Elf = Join-Path $Root "work\bin\EMAIN.elf"
$OutDir = Join-Path $Root "work\soak"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$mingw = Get-ChildItem -Path (Join-Path $Root "tools\llvm-mingw") -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "bin" } |
    Where-Object { Test-Path (Join-Path $_ "clang.exe") } |
    Select-Object -First 1
if (-not $mingw) { throw "LLVM-MinGW not found under tools\llvm-mingw." }
$env:PATH = "$mingw;$env:PATH"
$env:PS3_HEADLESS = "1"

$rows = @()
for ($i = 1; $i -le $Runs; $i++) {
    $log = Join-Path $OutDir "run$i.log"
    Remove-Item $log -ErrorAction SilentlyContinue

    $p = Start-Process -FilePath $Exe -ArgumentList @($Elf) -WorkingDirectory $Root `
        -RedirectStandardOutput $log -RedirectStandardError "$log.err" -NoNewWindow -PassThru
    if (-not $p.WaitForExit($Seconds * 1000)) {
        Stop-Process -Id $p.Id -Force
        Start-Sleep -Milliseconds 300
    }

    # Merge stderr after the process is gone so the parser sees one file.
    if (Test-Path "$log.err") {
        Get-Content "$log.err" -ErrorAction SilentlyContinue | Add-Content $log
        Remove-Item "$log.err" -ErrorAction SilentlyContinue
    }

    $text = Get-Content $log -Raw -ErrorAction SilentlyContinue
    if ($null -eq $text) { $text = "" }
    $initLines = [regex]::Matches($text, '\[init\] step(\d+)')
    $lastStep = if ($initLines.Count) { [int]$initLines[$initLines.Count - 1].Groups[1].Value } else { 0 }
    # The chain checks the flag after every stage. The run is gated by the
    # first non-zero value, not by the last check (which is usually 0 again).
    $flags = [regex]::Matches($text, '\[init\] flag=0x([0-9A-Fa-f]+)')
    $gate = 0
    if ($flags.Count) {
        $gate = ($flags | ForEach-Object { [Convert]::ToInt32($_.Groups[1].Value, 16) } |
            Where-Object { $_ -ne 0 } | Select-Object -First 1)
    }
    $flag = if ($null -ne $gate) { "{0:X2}" -f $gate } else { "-" }
    $scripts = ([regex]::Matches($text, "scripts/gt6")).Count
    $vol = ([regex]::Matches($text, "GT\.VOL")).Count
    $cellfs = ([regex]::Matches($text, "\[cellFs\]")).Count
    $ctorBad = ([regex]::Matches($text, "\[ctor\] BAD")).Count
    $flips = ([regex]::Matches($text, "PrepareFlip|SetFlip|flip_pending", "IgnoreCase")).Count
    $exits = ([regex]::Matches($text, "sys_process_exit")).Count
    $missing = ([regex]::Matches($text, "unresolved NID|missing HLE|no handler")).Count
    $pm = ([regex]::Matches($text, "PM resolved")).Count
    $pmMiss = ([regex]::Matches($text, "PM NOT LIFTED")).Count
    $rc = if ($text -match 'ppu_run returned (-?\d+)') { $Matches[1] } else { "-" }

    $rows += [pscustomobject]@{
        Run = $i; LastInitStep = $lastStep; GateFlag = $flag; ScriptOpens = $scripts
        VolMentions = $vol; CellFs = $cellfs; CtorBad = $ctorBad; FlipLines = $flips
        ProcessExits = $exits; MissingHLE = $missing; PMResolved = $pm; PMMissing = $pmMiss
        RunRC = $rc; Log = $log
    }
    Write-Host ("run {0}: step={1} gateflag=0x{2} scripts={3} vol={4} cellfs={5} ctorbad={6} flips={7} pm={8} miss={9} rc={10}" -f `
        $i, $lastStep, $flag, $scripts, $vol, $cellfs, $ctorBad, $flips, $pm, $missing, $rc)
}

$rows | Format-Table -AutoSize
Write-Host "Logs: $OutDir"
