# Reproducible third_party setup: clone the pinned commit, apply the patch, verify.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/setup-third-party.ps1 [-Check]
#   (no switch) create/repair third_party/<name> so it equals pinned commit + patch
#   -Check      verify only, change nothing; exit 1 if the tree differs from the pin
# Source of truth: third_party.lock (name|repo|tag|commit|patch). Idempotent.
param([switch]$Check)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$fail = 0
function Invoke-GitC { param([string]$Dir) & git -C $Dir @args 2>&1; if ($LASTEXITCODE) { throw "git $args failed in $Dir" } }

foreach ($line in Get-Content (Join-Path $Root "third_party.lock") | Where-Object { $_ -and $_ -notmatch '^\s*#' }) {
    $name, $repo, $tag, $commit, $patch = $line.Split('|')
    $dir = Join-Path $Root "third_party\$name"
    $patchFile = Join-Path $Root $patch
    if (-not (Test-Path $patchFile)) { throw "patch missing: $patch" }

    if (-not (Test-Path (Join-Path $dir ".git"))) {
        if ($Check) { Write-Host "[$name] MISSING (run without -Check)"; $fail = 1; continue }
        # atomic: clone to a temp dir, rename only when the pin is reached
        $tmp = "$dir.tmp"
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        New-Item -ItemType Directory -Force (Split-Path $dir) | Out-Null
        git clone --quiet $repo $tmp;           if ($LASTEXITCODE) { throw "clone failed" }
        git -C $tmp checkout --quiet $commit;   if ($LASTEXITCODE) { throw "pinned commit $commit not found" }
        git -C $tmp apply --whitespace=nowarn $patchFile; if ($LASTEXITCODE) { throw "patch does not apply to $commit" }
        Move-Item $tmp $dir
        Write-Host "[$name] created: $tag ($($commit.Substring(0,7))) + $(Split-Path -Leaf $patch)"
        continue
    }

    $head = (Invoke-GitC $dir rev-parse HEAD).Trim()
    if ($head -ne $commit) { Write-Host "[$name] HEAD $head != pin $commit"; $fail = 1; continue }
    # applied state: reverse patch must apply cleanly to the working tree
    git -C $dir apply --reverse --check --whitespace=nowarn $patchFile 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "[$name] OK: $tag + patch applied"; continue }
    git -C $dir apply --check --whitespace=nowarn $patchFile 2>$null
    if ($LASTEXITCODE -eq 0 -and -not $Check) {
        git -C $dir apply --whitespace=nowarn $patchFile
        Write-Host "[$name] patch applied"; continue
    }
    Write-Host "[$name] DIFFERS from pin+patch (local edits?)"; $fail = 1
}
exit $fail
