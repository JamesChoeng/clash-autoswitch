# clashpilot bootstrap installer (Windows / PowerShell).
#
# Makes the environment self-sufficient before installing clashpilot:
#   1. detect Python >= 3.8 (py launcher / python3 / python); install it if missing
#   2. detect git;  install it if missing
#   3. ensure pipx
#   4. pipx install clashpilot
#
# Run it without cloning anything:
#   irm https://raw.githubusercontent.com/JamesChoeng/clashpilot/main/install.ps1 | iex
#
# Env overrides:
#   CLASHPILOT_REPO  - source to install from (default: the GitHub repo)
#   CLASHPILOT_PY_VERSION - Python version to install when missing (default 3.12)

$ErrorActionPreference = 'Stop'

$RepoUrl     = if ($env:CLASHPILOT_REPO) { $env:CLASHPILOT_REPO } else { 'git+https://github.com/JamesChoeng/clashpilot.git' }
$PyVersion   = if ($env:CLASHPILOT_PY_VERSION) { $env:CLASHPILOT_PY_VERSION } else { '3.12' }
$MinMajor    = 3
$MinMinor    = 8

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Note($m) { Write-Host "    $m" -ForegroundColor DarkGray }
function Write-Warn($m) { Write-Host "warning: $m" -ForegroundColor Yellow }

# Pull the freshest user+machine PATH from the registry into this session, so a
# package manager that just installed Python/git becomes visible without a restart.
function Sync-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ } ) -join ';'
}

# Return a hashtable @{ Exe=...; Args=@(...) } for a Python that meets the
# minimum version, or $null. Skips the Microsoft Store "python" alias stub.
function Find-Python {
    $candidates = @(
        @{ Exe = 'py';      Args = @('-3') },
        @{ Exe = 'python3'; Args = @() },
        @{ Exe = 'python';  Args = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        $probe = @($c.Args + @('-c', 'import sys; print("%d.%d" % sys.version_info[:2])'))
        try { $out = & $c.Exe @probe 2>$null } catch { continue }
        if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
        $parts = ($out | Select-Object -First 1).Trim().Split('.')
        if ($parts.Count -lt 2) { continue }
        $maj = [int]$parts[0]; $min = [int]$parts[1]
        if ($maj -gt $MinMajor -or ($maj -eq $MinMajor -and $min -ge $MinMinor)) {
            return $c
        }
    }
    return $null
}

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Install-WithWinget($id) {
    if (-not (Test-Command 'winget')) { return $false }
    Write-Note "winget install $id"
    winget install -e --id $id --source winget `
        --accept-package-agreements --accept-source-agreements `
        --scope user 2>$null
    # winget returns non-zero for "already installed" too; trust a re-probe instead.
    Sync-Path
    return $true
}

function Install-Python {
    Write-Step "Python >= $MinMajor.$MinMinor not found - installing $PyVersion"
    if (Install-WithWinget "Python.Python.$PyVersion") {
        if (Find-Python) { return }
    }
    # Fallback: download the official installer and run it silently (per-user).
    Write-Note 'winget unavailable or failed; downloading installer from python.org'
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { 'win32' }
    # Resolve the newest patch release for the requested minor version.
    $index = (Invoke-WebRequest "https://www.python.org/ftp/python/" -UseBasicParsing).Links.href
    $patch = $index `
        | Where-Object { $_ -match "^$([regex]::Escape($PyVersion))\.\d+/$" } `
        | ForEach-Object { $_.TrimEnd('/') } `
        | Sort-Object { [int]($_.Split('.')[-1]) } -Descending `
        | Select-Object -First 1
    if (-not $patch) { throw "could not resolve a $PyVersion.x release from python.org" }
    $url = "https://www.python.org/ftp/python/$patch/python-$patch-$arch.exe"
    $exe = Join-Path $env:TEMP "python-$patch-$arch.exe"
    Write-Note "downloading $url"
    Invoke-WebRequest $url -OutFile $exe -UseBasicParsing
    Write-Note 'running installer (quiet, per-user, PrependPath)'
    Start-Process -FilePath $exe -Wait -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_pip=1'
    )
    Sync-Path
    if (-not (Find-Python)) { throw 'Python install completed but no usable interpreter was found' }
}

function Install-Git {
    Write-Step 'git not found - installing'
    if (Install-WithWinget 'Git.Git') {
        if (Test-Command 'git') { return }
    }
    Write-Warn 'could not install git automatically. Install it from https://git-scm.com/downloads and re-run.'
    throw 'git is required to install clashpilot from GitHub'
}

# --- Main --------------------------------------------------------------------

Sync-Path

$py = Find-Python
if (-not $py) {
    Install-Python
    $py = Find-Python
}
$pyDisplay = & $py.Exe @($py.Args + @('-V')) 2>&1
Write-Step "Using $($pyDisplay)"

if (-not (Test-Command 'git')) { Install-Git }

Write-Step 'Ensuring pipx'
& $py.Exe @($py.Args + @('-m', 'pip', 'install', '--user', '--upgrade', 'pip', 'pipx'))
& $py.Exe @($py.Args + @('-m', 'pipx', 'ensurepath')) 2>$null
Sync-Path

Write-Step "Installing clashpilot from $RepoUrl"
& $py.Exe @($py.Args + @('-m', 'pipx', 'install', '--force', $RepoUrl))
Sync-Path

Write-Step 'Registering Cursor startup hook'
$clashpilotCmd = Get-Command 'clashpilot' -ErrorAction SilentlyContinue
if ($clashpilotCmd) {
    & $clashpilotCmd.Source install-cursor-hook
} else {
    $fallback = Join-Path $env:USERPROFILE '.local\bin\clashpilot.exe'
    if (Test-Path $fallback) {
        & $fallback install-cursor-hook
    } else {
        Write-Warn 'could not find clashpilot on PATH yet; open a new terminal and run: clashpilot install-cursor-hook'
    }
}

Write-Host ''
Write-Step 'Done. Open Cursor to auto-start clashpilot, or run now:  clashpilot up'
