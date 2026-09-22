# Pure(ish) logic for the Windows installer (M7-PACK-DEPLOY-140). Dot-sourced
# by install.ps1 and uninstall.ps1, and by install.Tests.ps1 in isolation —
# same split as deploy/linux/lib.sh: every function here returns a value or a
# boolean with no side effect beyond what its name says, so it is testable
# without a real machine to install onto. Set-AskwellEnvPasswords is the one
# function with a real side effect (it rewrites a file), for the same reason
# lib.sh's generate_env_passwords is: "does the written .env still have every
# change-me placeholder" has no other observable shape.
#
# Podman on Windows only runs containers inside a WSL2 (or Hyper-V) virtual
# machine — there is no native Windows container runtime — so "is the runtime
# installed" here also has to answer "can a runtime exist on this machine at
# all", which Linux never has to ask.

$script:AskwellMinPodmanVersion = '4.3'

function Write-AskwellSay {
    param([string]$Message)
    Write-Host $Message
}

function Write-AskwellDie {
    param([string]$Message)
    Write-Host "askwell-install: $Message" -ForegroundColor Red
}

# ---------------------------------------------------------------- virtualisation

# WSL2 needs the CPU virtualisation extension exposed to Windows itself
# (Intel VT-x / AMD-V) *and* enabled in firmware — the second of which
# Windows can detect but never fix, because it is a BIOS/UEFI setting no
# installer running inside the OS can reach. Parsed from `systeminfo`'s own
# "Hyper-V Requirements" block rather than a CIM/WMI property, because that
# block's two wordings are stable across Windows versions and documented
# behaviour, not an internal property name this file would be guessing at:
#
#   Hyper-V Requirements:      VM Monitor Mode Extensions: Yes
#                               Virtualization Enabled In Firmware: Yes
#                               ...
#
# or, once a hypervisor (Hyper-V, WSL2's own) is already running:
#
#   Hyper-V Requirements:      A hypervisor has been detected. Features
#                               required for Hyper-V will not be displayed.
#
# The second form means virtualisation is not merely enabled but already in
# active use, which is a stronger yes than the firmware flag alone.
function Test-AskwellVirtualizationEnabled {
    param([string]$SystemInfoOutput)
    if ($SystemInfoOutput -match 'A hypervisor has been detected') { return $true }
    if ($SystemInfoOutput -match 'Virtualization Enabled In Firmware:\s*Yes') { return $true }
    return $false
}

# The Windows build number WSL2 requires. Anything older only has WSL1, which
# cannot run Podman's Linux VM at all.
$script:AskwellMinWindowsBuild = 19041

function Test-AskwellWindowsBuildSupported {
    param([int]$BuildNumber)
    return $BuildNumber -ge $script:AskwellMinWindowsBuild
}

# ---------------------------------------------------------------- versions

# Compares two dotted version strings. Returns -1, 0 or 1. Mirrors
# deploy/linux/lib.sh's version_compare (missing components compare as 0, so
# "5" -eq "5.0.0") so the two installers refuse on the same rule.
function Compare-AskwellVersion {
    param([string]$A, [string]$B)
    $av = $A -split '\.' | ForEach-Object { [int]$_ }
    $bv = $B -split '\.' | ForEach-Object { [int]$_ }
    $n = [Math]::Max($av.Count, $bv.Count)
    for ($i = 0; $i -lt $n; $i++) {
        $x = if ($i -lt $av.Count) { $av[$i] } else { 0 }
        $y = if ($i -lt $bv.Count) { $bv[$i] } else { 0 }
        if ($x -gt $y) { return 1 }
        if ($x -lt $y) { return -1 }
    }
    return 0
}

function Test-AskwellVersionAtLeast {
    param([string]$Version, [string]$Minimum)
    return (Compare-AskwellVersion $Version $Minimum) -ne -1
}

# Parses `podman --version`'s "podman version 4.9.4" into "4.9.4".
function ConvertFrom-AskwellPodmanVersion {
    param([string]$RawOutput)
    $match = [regex]::Match($RawOutput, '\d+(\.\d+){1,2}')
    if ($match.Success) { return $match.Value }
    return $null
}

function Test-AskwellPodmanMeetsMinimum {
    param([string]$RawOutput)
    $parsed = ConvertFrom-AskwellPodmanVersion $RawOutput
    if (-not $parsed) { return $false }
    return Test-AskwellVersionAtLeast $parsed $script:AskwellMinPodmanVersion
}

# ---------------------------------------------------------------- disk space

function Get-AskwellRequiredInstallBytes {
    if ($env:ASKWELL_REQUIRED_INSTALL_BYTES) { return [int64]$env:ASKWELL_REQUIRED_INSTALL_BYTES }
    return [int64]8000000000
}

function Format-AskwellBytes {
    param([int64]$Bytes)
    $units = 'B', 'KB', 'MB', 'GB', 'TB'
    $value = [double]$Bytes
    $u = 0
    while ($value -ge 1024 -and $u -lt 4) {
        $value /= 1024
        $u++
    }
    return "{0:N1} {1}" -f $value, $units[$u]
}

# ---------------------------------------------------------------- paths

# Windows' legacy MAX_PATH. A path at or past this fails to open unless the
# caller opts into the \\?\ long-path prefix or the machine's long-paths
# policy is on — neither of which Askwell's own install paths may assume, so
# every generated path is checked against it rather than hoped under it.
$script:AskwellMaxPath = 260

function Test-AskwellPathWithinLimit {
    param([string]$Path)
    return $Path.Length -lt $script:AskwellMaxPath
}

# Plain concatenation, not Join-Path: Join-Path resolves its base argument
# through the current provider, and a drive-qualified Windows string like
# `C:\Users\anna\AppData\Local` sent through the FileSystem provider on a
# non-Windows pwsh (this file's own unit tests, run on the Linux build host)
# errors with "Cannot find drive" because no `C:` PSDrive exists there. These
# four functions only ever build a string, never touch the filesystem, so
# there is nothing Join-Path's provider awareness buys here.
function Join-AskwellWindowsPath {
    param([string]$Base, [string]$Child)
    return "$($Base.TrimEnd('\'))\$Child"
}

function Get-AskwellDataDir {
    if ($env:ASKWELL_DATA_DIR) { return $env:ASKWELL_DATA_DIR }
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-AskwellWindowsPath $HOME 'AppData\Local' }
    return Join-AskwellWindowsPath $base 'Askwell'
}

function Get-AskwellInstallPrefix {
    if ($env:ASKWELL_INSTALL_PREFIX) { return $env:ASKWELL_INSTALL_PREFIX }
    $base = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { Join-AskwellWindowsPath $HOME 'AppData\Local' }
    return Join-AskwellWindowsPath $base 'Askwell\app'
}

function Get-AskwellStartMenuDir {
    if ($env:ASKWELL_START_MENU_DIR) { return $env:ASKWELL_START_MENU_DIR }
    $base = if ($env:APPDATA) { $env:APPDATA } else { Join-AskwellWindowsPath $HOME 'AppData\Roaming' }
    return Join-AskwellWindowsPath $base 'Microsoft\Windows\Start Menu\Programs'
}

function Get-AskwellStartupDir {
    if ($env:ASKWELL_STARTUP_DIR) { return $env:ASKWELL_STARTUP_DIR }
    $base = if ($env:APPDATA) { $env:APPDATA } else { Join-AskwellWindowsPath $HOME 'AppData\Roaming' }
    return Join-AskwellWindowsPath $base 'Microsoft\Windows\Start Menu\Programs\Startup'
}

function Get-AskwellInstallRecordPath {
    param([string]$DataDir)
    return Join-Path $DataDir 'install.json'
}

# ---------------------------------------------------------------- state

function Test-AskwellPreviousInstall {
    param([string]$DataDir)
    return Test-Path (Get-AskwellInstallRecordPath $DataDir)
}

function Get-AskwellPreviousInstallVersion {
    param([string]$DataDir)
    $recordPath = Get-AskwellInstallRecordPath $DataDir
    if (-not (Test-Path $recordPath)) { return $null }
    $record = Get-Content $recordPath -Raw | ConvertFrom-Json
    return $record.version
}

function Write-AskwellInstallRecord {
    param([string]$DataDir, [string]$Version, [string]$Method)
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $record = [ordered]@{
        version      = $Version
        method       = $Method
        installed_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        data_dir     = $DataDir
    }
    $record | ConvertTo-Json | Set-Content -Path (Get-AskwellInstallRecordPath $DataDir) -Encoding utf8
}

# ---------------------------------------------------------------- secrets

function New-AskwellRandomHex {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return ($buffer | ForEach-Object { $_.ToString('x2') }) -join ''
}

# Replaces every literal `change-me*` placeholder in a freshly-copied .env
# with a generated random value — the same fix as lib.sh's
# generate_env_passwords (issue #584), and the same pairing rule:
# SANDBOX_OWNER_PASSWORD/ASKWELL_SANDBOX_OWNER_PASSWORD and
# SANDBOX_READONLY_PASSWORD/ASKWELL_SANDBOX_READONLY_PASSWORD name the same
# credential twice and must stay equal.
function Set-AskwellEnvPasswords {
    param([string]$EnvFile)
    $postgresPassword = New-AskwellRandomHex
    $postgresAppPassword = New-AskwellRandomHex
    $postgresReadonlyPassword = New-AskwellRandomHex
    $sandboxPostgresPassword = New-AskwellRandomHex
    $sandboxOwnerPassword = New-AskwellRandomHex
    $sandboxReadonlyPassword = New-AskwellRandomHex

    $lines = Get-Content $EnvFile
    $lines = $lines | ForEach-Object {
        switch -Regex ($_) {
            '^POSTGRES_PASSWORD=' { "POSTGRES_PASSWORD=$postgresPassword"; continue }
            '^POSTGRES_APP_PASSWORD=' { "POSTGRES_APP_PASSWORD=$postgresAppPassword"; continue }
            '^POSTGRES_READONLY_PASSWORD=' { "POSTGRES_READONLY_PASSWORD=$postgresReadonlyPassword"; continue }
            '^SANDBOX_POSTGRES_PASSWORD=' { "SANDBOX_POSTGRES_PASSWORD=$sandboxPostgresPassword"; continue }
            '^SANDBOX_OWNER_PASSWORD=' { "SANDBOX_OWNER_PASSWORD=$sandboxOwnerPassword"; continue }
            '^SANDBOX_READONLY_PASSWORD=' { "SANDBOX_READONLY_PASSWORD=$sandboxReadonlyPassword"; continue }
            '^ASKWELL_SANDBOX_OWNER_PASSWORD=' { "ASKWELL_SANDBOX_OWNER_PASSWORD=$sandboxOwnerPassword"; continue }
            '^ASKWELL_SANDBOX_READONLY_PASSWORD=' { "ASKWELL_SANDBOX_READONLY_PASSWORD=$sandboxReadonlyPassword"; continue }
            default { $_ }
        }
    }
    Set-Content -Path $EnvFile -Value $lines -Encoding utf8
}

# ---------------------------------------------------------------- supervision (M7-PACK-DEPLOY-142)

# Task names as their own functions, not inline literals, so install.ps1,
# uninstall.ps1 and this file's own tests all name the same two Scheduled
# Tasks and cannot drift apart.
function Get-AskwellStackTaskName {
    return 'AskwellStack'
}

function Get-AskwellInferenceTaskName {
    return 'AskwellInference'
}

# The argument string `New-ScheduledTaskAction -Argument` passes to the
# resolved `podman.exe`. Built as its own pure function — same reasoning as
# `Get-AskwellStackTaskArguments`'s Linux/macOS counterparts
# (`systemd_stack_unit_contents`, `launch_agent_stack_plist_contents`):
# `podman compose up -d` returns immediately, leaving nothing for the
# scheduled task's restart-on-failure to watch, so this runs compose in the
# foreground and relies on `--abort-on-container-exit` to turn "a container
# died" into "the task's own process exited non-zero".
function Get-AskwellStackTaskArguments {
    param([string]$ComposePath, [string]$EnvPath)
    return "compose -f `"$ComposePath`" --env-file `"$EnvPath`" up --abort-on-container-exit"
}

# The argument string passed to the resolved Python interpreter to run
# `deploy/inference/askwell-inference` (a standard-library-only script, same
# as Linux/macOS — see that file's own header). This task restarts the outer
# Python process if it is killed or crashes outright; the script's own
# five-step backoff for a failed llama.cpp spawn happens inside that process
# and is unaffected by whether this task ever fires.
function Get-AskwellInferenceTaskArguments {
    param([string]$ScriptPath)
    return "`"$ScriptPath`""
}

# ---------------------------------------------------------------- quarantine

# Whether a file that should exist after a plain copy is missing is, on its
# own, ambiguous — a bad release tree looks identical to Defender having
# lifted the file a moment after Copy-Item returned. This names the two real
# causes rather than a generic "file not found", because the fix for each is
# different (rebuild vs. restore-from-quarantine) and a lawyer on a firm
# laptop cannot tell them apart from a bare error.
function Get-AskwellQuarantineMessage {
    param([string]$FileName)
    return "$FileName is missing after being placed. If antivirus software " +
    "removed it, check its quarantine or threat history for $FileName and " +
    "restore it, then add an exclusion for the Askwell install folder so " +
    "this does not repeat — Askwell's native inference binary and its " +
    "unsigned desktop shell are both unfamiliar executables an antivirus " +
    "product has never seen before, which is exactly what quarantine " +
    "heuristics flag. If it is not in quarantine, the release tree itself " +
    "is missing this file and needs rebuilding."
}

# ---------------------------------------------------------------- generated files

function Get-AskwellShortcutTarget {
    param([string]$ExePath)
    return $ExePath
}

function Get-AskwellUninstallRegistryValues {
    param([string]$Version, [string]$UninstallCommand, [string]$InstallPrefix)
    return [ordered]@{
        DisplayName     = 'Askwell'
        DisplayVersion  = $Version
        Publisher       = 'Askwell'
        UninstallString = $UninstallCommand
        InstallLocation = $InstallPrefix
        NoModify        = 1
        NoRepair        = 1
    }
}
