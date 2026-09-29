<#
.SYNOPSIS
    The one-click path: puts every prerequisite in place, then runs
    install.ps1 unattended. Run by Askwell-Setup-<version>.exe, never by hand.

.DESCRIPTION
    install.ps1 is correct but was written to be run from a terminal, and two
    of its paths end with "close this terminal, open a new one and run the
    installer again": after winget installs Podman or Docker Compose, the
    running session cannot see them, because Windows only hands a new PATH to
    new sessions. A double-click installer has no terminal to reopen.

    So this runs first, installs what is missing, and refreshes PATH in its
    own process from the registry, the same values a new session would read.
    By the time install.ps1 runs, everything it checks for is already present
    and none of those dead ends can be reached. install.ps1's own checks are
    unchanged and still run: this adds nothing to what it verifies, only
    removes the reasons it would stop.

    What it still cannot do in one pass, and says so plainly:
      - turn on CPU virtualisation, which is a firmware setting;
      - finish enabling WSL, which needs Windows to restart. It enables WSL,
        exits with 30, and the setup asks for a restart and a second run.

    Exit codes read by the setup exe:
       0  installed
      20  winget (App Installer) is missing
      21  Podman could not be installed
      22  Docker Compose could not be installed
      30  WSL was just enabled; Windows must restart, then run Setup again
      31  the Podman machine could not be started
      anything else: install.ps1's own exit code, its reason already printed
#>
param(
    [Parameter(Mandatory = $true)][string]$Root
)

$ErrorActionPreference = 'Continue'

# install.ps1's own helpers, so every check here is the one it will make.
. (Join-Path $Root 'deploy\windows\lib.ps1')

function Say([string]$Text) { Write-Output $Text }

function Update-AskwellPath {
    # What a freshly opened session would see: machine PATH, then user PATH.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-ComposeProvider {
    # The installer's own check, not a copy of it. 0.9.1 carried a rewritten
    # version that also rejected any output mentioning "podman-compose", and
    # podman prints that name in the banner it shows before every provider
    # ("Executing external compose provider ... Please see podman-compose(1)
    # for how to disable this message"). So it refused every working Docker
    # Compose, and Setup stopped with code 22 right after installing it
    # successfully. The first real Windows test found it. It also joined the
    # output into a single line, which the installer's line-anchored version
    # match cannot read. Calling install.ps1's function means the two can
    # never disagree again.
    if (-not (Test-Command 'podman')) { return $false }
    $out = (& podman compose version 2>&1 | ForEach-Object { "$_" }) -join "`n"
    if ($LASTEXITCODE -ne 0) { return $false }
    return [bool](Test-AskwellComposeMeetsMinimum $out)
}

function Install-WithWinget([string]$Id, [string]$Label) {
    Say "Installing $Label. This can take a few minutes..."
    & winget install -e --id $Id --silent --accept-source-agreements --accept-package-agreements 2>&1 |
        ForEach-Object { Say "  $_" }
    Update-AskwellPath
}

Say "Askwell setup is checking this PC."
Update-AskwellPath

if (-not (Test-Command 'winget')) {
    Say ("Windows' App Installer (winget) is missing. Install 'App Installer' from the " +
        "Microsoft Store, then run Askwell Setup again.")
    exit 20
}

if (-not (Test-Command 'podman')) {
    Install-WithWinget 'RedHat.Podman' 'Podman (runs Askwell''s local services)'
    if (-not (Test-Command 'podman')) {
        Say "Podman did not install. The messages above say why. Run Askwell Setup again once that is fixed."
        exit 21
    }
}
Say "Podman: $((& podman --version) -join ' ')"

# WSL is what Podman's machine runs in. On a PC that has never used it,
# enabling it needs a restart before the machine can be created.
& wsl.exe --status *> $null
if ($LASTEXITCODE -ne 0) {
    Say "Enabling the Windows Subsystem for Linux, which Podman needs..."
    & wsl.exe --install --no-distribution 2>&1 | ForEach-Object { Say "  $_" }
    Say "Windows needs to restart to finish enabling it."
    exit 30
}

if (-not (Test-ComposeProvider)) {
    Install-WithWinget 'Docker.DockerCompose' 'Docker Compose (starts Askwell''s services)'
    if (-not (Test-ComposeProvider)) {
        Say "Docker Compose did not install. The messages above say why. Run Askwell Setup again once that is fixed."
        exit 22
    }
}
Say "Compose provider: $((& podman compose version 2>&1) -join ' ')"

# The Podman machine: create it on first use, start it if stopped.
$machines = (& podman machine list --format '{{.Name}}' 2>$null) -join ''
if ([string]::IsNullOrWhiteSpace($machines)) {
    Say "Creating Podman's machine. This happens once and takes a few minutes..."
    & podman machine init 2>&1 | ForEach-Object { Say "  $_" }
}
$running = (& podman machine list --format '{{.Running}}' 2>$null) -join ' '
if ($running -notmatch 'true') {
    Say "Starting Podman's machine..."
    & podman machine start 2>&1 | ForEach-Object { Say "  $_" }
}
& podman info *> $null
if ($LASTEXITCODE -ne 0) {
    Say "Podman's machine did not start. Restart Windows and run Askwell Setup again."
    exit 31
}

Say "Everything Askwell needs is in place. Installing Askwell..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'deploy\windows\install.ps1') -Yes 2>&1 |
    ForEach-Object { Say $_ }
exit $LASTEXITCODE
