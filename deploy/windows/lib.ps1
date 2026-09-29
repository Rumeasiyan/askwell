# Pure(ish) logic for the Windows installer (M7-PACK-DEPLOY-140). Dot-sourced
# by install.ps1 and uninstall.ps1, and by install.Tests.ps1 in isolation -
# same split as deploy/linux/lib.sh: every function here returns a value or a
# boolean with no side effect beyond what its name says, so it is testable
# without a real machine to install onto. Set-AskwellEnvPasswords is the one
# function with a real side effect (it rewrites a file), for the same reason
# lib.sh's generate_env_passwords is: "does the written .env still have every
# change-me placeholder" has no other observable shape.
#
# Podman on Windows only runs containers inside a WSL2 (or Hyper-V) virtual
# machine - there is no native Windows container runtime - so "is the runtime
# installed" here also has to answer "can a runtime exist on this machine at
# all", which Linux never has to ask.

$script:AskwellMinPodmanVersion = '4.3'
# `podman compose` is only a front end for an external provider (issue #767);
# see deploy/linux/lib.sh for why the minimum is Docker Compose 2.20.
$script:AskwellMinComposeVersion = '2.20'

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
# (Intel VT-x / AMD-V) *and* enabled in firmware - the second of which
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

# Same contract as deploy/linux/lib.sh's parse_compose_provider_version:
# "Docker Compose version v5.1.1" gives "5.1.1", and any other provider
# gives nothing, because only docker-compose is verified with this stack.
function ConvertFrom-AskwellComposeVersion {
    param([string]$RawOutput)
    $match = [regex]::Match($RawOutput, '(?m)^Docker Compose version v?(\d+(\.\d+){1,2})')
    if ($match.Success) { return $match.Groups[1].Value }
    return $null
}

function Test-AskwellComposeMeetsMinimum {
    param([string]$RawOutput)
    $parsed = ConvertFrom-AskwellComposeVersion $RawOutput
    if (-not $parsed) { return $false }
    return Test-AskwellVersionAtLeast $parsed $script:AskwellMinComposeVersion
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
# policy is on - neither of which Askwell's own install paths may assume, so
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
    $record = Get-Content $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
    return $record.version
}

# UTF-8 without a byte-order mark, under Windows PowerShell 5.1 as under 7.
# 5.1's `Set-Content -Encoding utf8` writes a BOM, which becomes part of the
# first key in .env and makes the install record invalid JSON to a strict
# parser; 7's does not. Every file this installer writes goes through here.
function Write-AskwellUtf8File {
    param([string]$Path, [string[]]$Lines)
    $full = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
    [System.IO.File]::WriteAllLines($full, $Lines, (New-Object System.Text.UTF8Encoding $false))
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
    Write-AskwellUtf8File -Path (Get-AskwellInstallRecordPath $DataDir) -Lines @($record | ConvertTo-Json)
}

# ---------------------------------------------------------------- secrets

function New-AskwellRandomHex {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return ($buffer | ForEach-Object { $_.ToString('x2') }) -join ''
}

# Replaces every literal `change-me*` placeholder in a freshly-copied .env
# with a generated random value - the same fix as lib.sh's
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

    $lines = Get-Content $EnvFile -Encoding UTF8
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
    Write-AskwellUtf8File -Path $EnvFile -Lines $lines
}

# The three Redis passwords (`M8-FIX-SEC-177`, issue #730) - lib.sh's
# ensure_redis_passwords, same rule: every install, upgrades included; a
# missing, empty or `change-me*` value is generated, a real one is left alone.
# Safe to replace because Redis keeps no users between starts -
# deploy/redis/start.sh renders them from .env every time.
function Set-AskwellRedisPasswords {
    param([string]$EnvFile)
    $lines = @(Get-Content $EnvFile -Encoding UTF8)
    $commented = $false
    foreach ($name in @('REDIS_API_PASSWORD', 'REDIS_WORKER_PASSWORD', 'REDIS_PROXY_PASSWORD')) {
        $pattern = "^$name="
        $existing = @($lines | Where-Object { $_ -match $pattern })
        $value = if ($existing.Count -gt 0) { ($existing[-1] -split '=', 2)[1] } else { '' }
        if ($value -and -not $value.StartsWith('change-me')) { continue }
        $generated = "$name=$(New-AskwellRandomHex)"
        if ($existing.Count -gt 0) {
            $lines = @($lines | ForEach-Object { if ($_ -match $pattern) { $generated } else { $_ } })
        } else {
            if (-not $commented) {
                $lines += @('', '', '# Redis, one user per service - generated by the installer (M8-FIX-SEC-177).')
                $commented = $true
            }
            $lines += $generated
        }
    }
    Write-AskwellUtf8File -Path $EnvFile -Lines $lines
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
# resolved `podman.exe`. Built as its own pure function - same reasoning as
# `Get-AskwellStackTaskArguments`'s Linux/macOS counterparts
# (`systemd_stack_unit_contents`, `launch_agent_stack_plist_contents`):
# `podman compose up -d` returns immediately, leaving nothing for the
# scheduled task's restart-on-failure to watch, so this runs compose in the
# foreground and relies on `--abort-on-container-exit` to turn "a container
# died" into "the task's own process exited non-zero". `--no-attach migrate`
# keeps the one service that is meant to exit from tripping that; see
# deploy/linux/lib.sh's systemd_stack_unit_contents (M9-FIX-DEPLOY-200).
function Get-AskwellStackTaskArguments {
    param([string]$ComposePath, [string]$EnvPath)
    return "compose -f `"$ComposePath`" --env-file `"$EnvPath`" up --abort-on-container-exit --no-attach migrate"
}

# The argument string passed to the resolved Python interpreter to run
# `deploy/inference/askwell-inference` (a standard-library-only script, same
# as Linux/macOS - see that file's own header). This task restarts the outer
# Python process if it is killed or crashes outright; the script's own
# five-step backoff for a failed llama.cpp spawn happens inside that process
# and is unaffected by whether this task ever fires.
function Get-AskwellInferenceTaskArguments {
    param([string]$ScriptPath)
    return "`"$ScriptPath`""
}

# ---------------------------------------------------------------- bundled images

# The container images a release artefact carries (M9-REL-DEPLOY-214),
# sorted by name. Same contract as deploy/linux/lib.sh's
# bundled_image_archives: a release saves every image compose.yaml names
# into `images\`, and a source checkout has none, so this returns nothing.
function Get-AskwellBundledImages {
    param([string]$Root)
    $dir = Join-Path $Root 'images'
    if (-not (Test-Path $dir -PathType Container)) { return @() }
    return @(Get-ChildItem -Path $dir -Filter '*.tar' -File | Sort-Object Name | ForEach-Object { $_.FullName })
}

# ---------------------------------------------------------------- database (M9-FIX-DEPLOY-200)

# Mirrors deploy/linux/lib.sh's database section; see it for the reasoning.
# The named volumes compose.yaml declares, as Podman names them (project
# `name: askwell`): the database, the imported-database sandbox, the queue,
# and /var/lib/askwell (stored backups, crash reports, traces).
$script:AskwellVolumes = @('askwell_postgres-data', 'askwell_sandbox-data', 'askwell_redis-data', 'askwell_askwell-state')

# compose's own one-shot `migrate` service (issue #698): `alembic upgrade
# head` as the owner role, starting Postgres first if it is not up. One quoted
# string, like Get-AskwellStackTaskArguments, because Start-Process joins an
# argument array without quoting and a profile path can contain a space.
function Get-AskwellMigrationArguments {
    param([string]$ComposePath, [string]$EnvPath)
    return "compose -f `"$ComposePath`" --env-file `"$EnvPath`" run --rm migrate"
}

# Runs the migration and returns its exit code, with stdout and stderr both
# in $LogPath (Alembic logs to stderr). Start-Process with redirected files
# rather than `2>&1`: under Windows PowerShell 5.1 with
# $ErrorActionPreference = 'Stop', a native command's stderr redirected that
# way becomes a terminating error, which would turn Alembic's ordinary INFO
# lines into an installer crash.
function Invoke-AskwellMigration {
    param([string]$Podman, [string]$ComposePath, [string]$EnvPath, [string]$LogPath)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath) | Out-Null
    $errPath = "$LogPath.stderr"
    $proc = Start-Process -FilePath $Podman -ArgumentList (Get-AskwellMigrationArguments $ComposePath $EnvPath) `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput $LogPath -RedirectStandardError $errPath
    if (Test-Path $errPath) {
        Get-Content $errPath | Add-Content $LogPath
        Remove-Item $errPath -Force
    }
    return $proc.ExitCode
}

# How many migrations a run applied, from Alembic's own "Running upgrade"
# lines. 0 is "already at head".
function Get-AskwellMigrationsApplied {
    param([string]$LogPath)
    if (-not (Test-Path $LogPath)) { return 0 }
    return @(Select-String -Path $LogPath -Pattern 'Running upgrade' -SimpleMatch).Count
}

# Where a plain uninstall keeps `.env` (issue #765); see deploy/linux/lib.sh's
# kept_env_path for the reasoning.
function Get-AskwellKeptEnvPath {
    param([string]$DataDir)
    return (Join-Path $DataDir 'askwell.env')
}

# Stops the stack's containers by the install's own compose files, before an
# upgrade migrates (issue #768). Returns podman's exit code.
function Stop-AskwellStackContainers {
    param([string]$Podman, [string]$ComposePath, [string]$EnvPath)
    $ErrorActionPreference = 'Continue'
    & $Podman compose -f $ComposePath --env-file $EnvPath down *> $null
    return $LASTEXITCODE
}

# Removes every volume in $script:AskwellVolumes by name (issue #700), so it
# works after compose.yaml has gone. Returns the names it could not remove -
# empty means every one is gone - so the caller reports only what happened.
# 'Continue' locally: `volume exists` answers "no" through its exit code, and
# must not become a terminating error under the callers' 'Stop'.
function Remove-AskwellVolumes {
    param([string]$Podman = 'podman')
    $ErrorActionPreference = 'Continue'
    $left = @()
    foreach ($volume in $script:AskwellVolumes) {
        & $Podman volume exists $volume *> $null
        if ($LASTEXITCODE -ne 0) { continue }
        & $Podman volume rm -f $volume *> $null
        & $Podman volume exists $volume *> $null
        if ($LASTEXITCODE -eq 0) { $left += $volume }
    }
    return ,$left
}

# ---------------------------------------------------------------- quarantine

# Whether a file that should exist after a plain copy is missing is, on its
# own, ambiguous - a bad release tree looks identical to Defender having
# lifted the file a moment after Copy-Item returned. This names the two real
# causes rather than a generic "file not found", because the fix for each is
# different (rebuild vs. restore-from-quarantine) and a lawyer on a firm
# laptop cannot tell them apart from a bare error.
function Get-AskwellQuarantineMessage {
    param([string]$FileName)
    return "$FileName is missing after being placed. If antivirus software " +
    "removed it, check its quarantine or threat history for $FileName and " +
    "restore it, then add an exclusion for the Askwell install folder so " +
    "this does not repeat - Askwell's native inference binary and its " +
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

# ---------------------------------------------------------------- setup: WSL and the one restart
# Used by setup\setup-bootstrap.ps1, kept here so install.test.ps1 can test it.

# Whether WSL can run Podman's machine yet, from the state Windows itself
# reports for the VirtualMachinePlatform feature (Get-WindowsOptionalFeature).
# 0.9.3 asked `wsl --status` instead, which fails whenever no Linux
# distribution is installed - and Setup installs WSL with none on purpose,
# because Podman creates its own. So after every restart it asked for
# another one. Only Windows saying "EnablePending" means a restart will help.
#   'ready'   - enabled, nothing pending
#   'restart' - enabled, waiting for Windows to restart
#   'missing' - anything else: not enabled, or the state could not be read
function Get-AskwellWslState {
    param([string]$VmPlatformState)
    switch ($VmPlatformState) {
        'Enabled' { return 'ready' }
        'EnablePending' { return 'restart' }
        default { return 'missing' }
    }
}

# Where Setup keeps its files across the restart. The exe unpacks to %TEMP%,
# which it deletes when it closes, so the continuation needs its own copy.
function Get-AskwellSetupStageDir {
    param([string]$ProgramData)
    return "$($ProgramData.TrimEnd('\'))\AskwellSetup"
}

# The command Windows runs once, at the next sign-in, to finish the install.
# RunOnce values are limited to 260 characters, which is why -Root is not
# passed: the bootstrap finds its root from its own location.
function Get-AskwellResumeCommand {
    param([string]$SystemRoot, [string]$StageDir)
    # Plain strings, not Join-Path: these are paths for Windows to run later,
    # and Join-Path resolves the drive, which install.test.ps1 cannot offer.
    $powershell = "$($SystemRoot.TrimEnd('\'))\System32\WindowsPowerShell\v1.0\powershell.exe"
    $script = "$($StageDir.TrimEnd('\'))\deploy\windows\setup\setup-bootstrap.ps1"
    return "`"$powershell`" -NoProfile -ExecutionPolicy Bypass -File `"$script`" -Resume"
}

# ---------------------------------------------------------------- setup: the failure report
# When Setup fails, it saves a plain-text report on the Desktop for the person
# to send to whoever gave them Askwell. Nothing is sent by Setup itself
# (docs/decisions.md, 2026-09-29). The people testing Setup are not expected
# to read a log or describe an error, so the report has to carry everything a
# maintainer needs: what failed, on what Windows, and every line Setup printed.

# A plain hashtable: [ordered] would read an integer key as a position.
$script:AskwellSetupCodeMeanings = @{
    20 = "winget (Windows' App Installer) is missing"
    21 = 'Podman could not be installed'
    22 = 'Docker Compose could not be installed'
    23 = "Setup's own files did not load"
    24 = 'Setup ran as 32-bit PowerShell'
    31 = "Podman's machine could not be started"
    32 = 'WSL could not be enabled'
    33 = 'WSL still waited for a restart after Setup restarted'
}

function Get-AskwellSetupCodeMeaning {
    param([int]$Code)
    if ($script:AskwellSetupCodeMeanings.ContainsKey($Code)) { return $script:AskwellSetupCodeMeanings[$Code] }
    return 'the Askwell installer (install.ps1) stopped; its reason is in the log below'
}

# The report goes to a person, maybe onward to a public issue, so the Windows
# account name, the profile path and the PC's name are replaced. Longest
# first, so the profile path is replaced whole rather than around the name
# inside it. A name shorter than three characters is left alone: replacing
# every "al" in a log would destroy it and hide very little.
function Protect-AskwellReportText {
    param([string]$Text, [string]$UserProfile, [string]$UserName, [string]$ComputerName)
    $pairs = @(
        [pscustomobject]@{ Find = $UserProfile; With = '<profile>' },
        [pscustomobject]@{ Find = $ComputerName; With = '<pc>' },
        [pscustomobject]@{ Find = $UserName; With = '<user>' }
    ) | Where-Object { $_.Find -and $_.Find.Length -ge 3 } | Sort-Object { - $_.Find.Length }
    foreach ($pair in $pairs) {
        $Text = [regex]::Replace($Text, [regex]::Escape($pair.Find), $pair.With, 'IgnoreCase')
    }
    return $Text
}

function Format-AskwellSetupReport {
    param([int]$Code, [System.Collections.IDictionary]$Facts, [string]$Log)
    $lines = @(
        'Askwell Setup report',
        '====================',
        '',
        'Askwell could not finish installing on this PC.',
        '',
        'Please send this file to whoever gave you Askwell. That is all you need',
        'to do; it tells them what went wrong. If you have a GitHub account, you',
        'can instead attach it to a new issue at',
        'https://github.com/Rumeasiyan/askwell/issues/new',
        '',
        "It holds Setup's own messages and basic facts about this PC (Windows",
        'version, memory, what Setup found installed). It holds none of your',
        'files. Your Windows account name and this PC''s name have been replaced',
        'with <user> and <pc>.',
        '',
        "Result: code $Code - $(Get-AskwellSetupCodeMeaning $Code)"
    )
    foreach ($key in $Facts.Keys) { $lines += ('{0}: {1}' -f $key, $Facts[$key]) }
    $lines += @('', '--- everything Setup printed ---', $Log)
    return ($lines -join "`r`n")
}
