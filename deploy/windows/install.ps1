<#
.SYNOPSIS
    Askwell's Windows installer. M7-PACK-DEPLOY-140.

.DESCRIPTION
    Checks virtualisation and Podman, places the stack, the native inference
    supervisor, the probe and the desktop shell, creates the data
    directories, registers Askwell to start with the session, and opens the
    Askwell window — never a browser tab. Mirrors deploy/linux/install.sh's
    shape; see that file's header for the artefact layout both installers
    share and issue #559 for the one artefact neither builds itself.

    What this script needs beside itself, and where it expects to find it:

      REPO_ROOT (two directories above this script)\
        compose.yaml, .env.example, deploy\postgres, deploy\sandbox   — the stack
        deploy\probe\askwell-probe                                    — the host probe
        deploy\inference\askwell-inference                             — native inference (a
                                                                          standard-library-only
                                                                          Python script; needs a
                                                                          Python on this host's
                                                                          PATH, same as Linux)
        web\src-tauri\target\release\askwell-shell.exe                  — the desktop shell

    Podman on Windows only runs containers inside a WSL2 virtual machine —
    there is no native Windows container runtime — so this checks
    virtualisation before Podman, and names the firmware setting to enable
    when it is off, since that is a BIOS/UEFI change no installer running
    inside Windows can make for the user.

    Never fetches a model. `winget`/Podman's own install may need the network
    to install or to pull container images — the same class of install-time
    exception `scripts/dev.sh lock`/`web-install` already name (AGENTS.md
    §5) — but nothing here ever reaches out for model weights.
#>

[CmdletBinding()]
param(
    [string]$DataDir,
    [string]$InstallPrefix,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $Here '..\..')
. (Join-Path $Here 'lib.ps1')

$Version = '0.0.0'
$versionFile = Join-Path $RepoRoot 'VERSION'
if (Test-Path $versionFile) { $Version = (Get-Content $versionFile -Raw).Trim() }

if (-not $DataDir) { $DataDir = Get-AskwellDataDir }
if (-not $InstallPrefix) { $InstallPrefix = Get-AskwellInstallPrefix }
$BinDir = Join-Path $InstallPrefix 'bin'
$StartMenuDir = Get-AskwellStartMenuDir
$StartupDir = Get-AskwellStartupDir

function Confirm-Askwell {
    param([string]$Prompt)
    if ($Yes) { return $true }
    $reply = Read-Host "$Prompt [y/N]"
    return $reply -match '^[yY]'
}

function Test-AskwellIsAdmin {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---------------------------------------------------------------- 1. virtualisation + runtime

function Test-AskwellRuntime {
    $sysinfo = systeminfo 2>$null | Out-String
    if (-not (Test-AskwellVirtualizationEnabled $sysinfo)) {
        Write-AskwellDie ("Virtualisation is off. Podman on Windows runs containers inside a " +
            "WSL2 virtual machine, which needs CPU virtualisation (Intel VT-x / AMD-V) turned " +
            "on in this PC's firmware. Restart, enter BIOS/UEFI setup (often Del, F2 or F10 at " +
            "boot), find the setting named 'Virtualization Technology', 'Intel VT-x', 'AMD-V' " +
            "or 'SVM Mode', enable it, save and reboot. Askwell cannot enable this itself — it " +
            "is a firmware setting, not a Windows one — then run this installer again.")
        exit 1
    }
    Write-AskwellSay 'Virtualisation is enabled.'

    $podman = Get-Command podman -ErrorAction SilentlyContinue
    if ($podman) {
        $reported = (& podman --version) -join ' '
        if (Test-AskwellPodmanMeetsMinimum $reported) {
            Write-AskwellSay "Podman found: $reported"
            return
        }
        Write-AskwellDie "Podman is installed but too old ($reported). Askwell needs Podman $script:AskwellMinPodmanVersion or newer. Upgrade it, then run this installer again."
        exit 1
    }

    if (-not (Test-AskwellIsAdmin)) {
        Write-AskwellDie ("Podman is not installed, and installing it needs an administrator " +
            "on Windows (it registers a WSL2 distribution). This account is not an " +
            "administrator. Ask whoever administers this machine to install Podman Desktop " +
            "(podman.io/docs/installation) or run this installer from an administrator " +
            "PowerShell, then run this installer again.")
        exit 1
    }

    Write-AskwellSay 'Podman is not installed. This installer needs to run:'
    Write-AskwellSay '  winget install -e --id RedHat.Podman'
    if (-not (Confirm-Askwell 'Install Podman now?')) {
        Write-AskwellDie 'Podman is required. Install it and re-run this installer.'
        exit 1
    }
    winget install -e --id RedHat.Podman
    $podman = Get-Command podman -ErrorAction SilentlyContinue
    if (-not $podman) {
        Write-AskwellDie ("Podman install finished but 'podman' is still not on PATH. Close " +
            "and reopen this terminal (winget updates PATH for new sessions only), then run " +
            "this installer again.")
        exit 1
    }
    Write-AskwellSay "Podman installed: $((& podman --version) -join ' ')"
}

# ---------------------------------------------------------------- 2. disk space

function Test-AskwellDiskSpace {
    $needed = Get-AskwellRequiredInstallBytes
    $rootQualifier = Split-Path -Qualifier $InstallPrefix
    $have = (Get-PSDrive -Name $rootQualifier.TrimEnd(':') -ErrorAction SilentlyContinue).Free
    if (-not $have) {
        Write-AskwellSay "Could not determine free disk space at $InstallPrefix; continuing without the check."
        return
    }
    if ($have -lt $needed) {
        Write-AskwellDie "Not enough disk space at $InstallPrefix`: need $(Format-AskwellBytes $needed), have $(Format-AskwellBytes $have). Free up space and run this installer again — nothing has been copied."
        exit 1
    }
    Write-AskwellSay "Disk space OK: $(Format-AskwellBytes $have) available, $(Format-AskwellBytes $needed) needed."
}

# ---------------------------------------------------------------- 3. previous install

function Test-AskwellPrevious {
    if (Test-AskwellPreviousInstall $DataDir) {
        $prev = Get-AskwellPreviousInstallVersion $DataDir
        if (-not $prev) { $prev = 'unknown' }
        Write-AskwellSay "Existing Askwell installation found (version $prev) at $DataDir. Its data is left untouched; upgrading application files in place."
    }
}

# ---------------------------------------------------------------- 4. required artefacts + path length

$ShellBin = Join-Path $RepoRoot 'web\src-tauri\target\release\askwell-shell.exe'

function Test-AskwellArtefacts {
    $missing = $false
    $required = @(
        (Join-Path $RepoRoot 'compose.yaml'),
        (Join-Path $RepoRoot 'deploy\probe\askwell-probe'),
        (Join-Path $RepoRoot 'deploy\inference\askwell-inference')
    )
    foreach ($path in $required) {
        if (-not (Test-Path $path)) {
            Write-AskwellSay "Missing: $path"
            $missing = $true
        }
    }
    if (-not (Test-Path $ShellBin)) {
        Write-AskwellSay "Missing: $ShellBin"
        Write-AskwellSay '  The desktop shell has not been built. Build it first with:'
        Write-AskwellSay "    cd $RepoRoot\web\src-tauri; cargo tauri build --no-bundle"
        $missing = $true
    }
    if ($missing) {
        Write-AskwellDie 'One or more required files are missing (listed above). This installer places what a release build produces; it does not build them. Nothing has been copied.'
        exit 1
    }

    # Windows' legacy MAX_PATH (260) fails a plain file open unless the
    # caller opts into \\?\ — checked against the destination path this
    # installer is about to create, not the source tree, since the
    # destination is the one this installer controls the length of.
    $destShell = Join-Path $InstallPrefix 'askwell-shell.exe'
    if (-not (Test-AskwellPathWithinLimit $destShell)) {
        Write-AskwellDie ("The install path is too long: $destShell is $($destShell.Length) " +
            "characters, past Windows' $($script:AskwellMaxPath)-character limit. Choose a " +
            "shorter -InstallPrefix (for example a folder closer to the drive root) and run " +
            "this installer again.")
        exit 1
    }
}

# ---------------------------------------------------------------- 5. place files

function Copy-AskwellFiles {
    New-Item -ItemType Directory -Force -Path $InstallPrefix | Out-Null
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallPrefix 'deploy\postgres') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallPrefix 'deploy\sandbox') | Out-Null

    Copy-Item (Join-Path $RepoRoot 'compose.yaml') (Join-Path $InstallPrefix 'compose.yaml') -Force

    $envFile = Join-Path $InstallPrefix '.env'
    if (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $RepoRoot '.env.example') $envFile
        Set-AskwellEnvPasswords $envFile
        Write-AskwellSay "Generated database credentials in $envFile"
    }

    Copy-Item (Join-Path $RepoRoot 'deploy\postgres\*') (Join-Path $InstallPrefix 'deploy\postgres\') -Recurse -Force
    Copy-Item (Join-Path $RepoRoot 'deploy\sandbox\*') (Join-Path $InstallPrefix 'deploy\sandbox\') -Recurse -Force

    $probeDest = Join-Path $InstallPrefix 'askwell-probe'
    Copy-Item (Join-Path $RepoRoot 'deploy\probe\askwell-probe') $probeDest -Force
    if (-not (Test-Path $probeDest)) {
        Write-AskwellDie (Get-AskwellQuarantineMessage 'askwell-probe')
        exit 1
    }

    $inferenceDest = Join-Path $InstallPrefix 'askwell-inference'
    Copy-Item (Join-Path $RepoRoot 'deploy\inference\askwell-inference') $inferenceDest -Force
    if (-not (Test-Path $inferenceDest)) {
        Write-AskwellDie (Get-AskwellQuarantineMessage 'askwell-inference')
        exit 1
    }

    $shellDest = Join-Path $InstallPrefix 'askwell-shell.exe'
    Copy-Item $ShellBin $shellDest -Force
    if (-not (Test-Path $shellDest)) {
        Write-AskwellDie (Get-AskwellQuarantineMessage 'askwell-shell.exe')
        exit 1
    }

    Write-AskwellSay "Application files placed under $InstallPrefix"
}

# ---------------------------------------------------------------- 6. data dirs

function New-AskwellDataDirs {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $DataDir 'models') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $DataDir 'logs') | Out-Null
    Write-AskwellSay "Data directory: $DataDir"
}

# ---------------------------------------------------------------- 7. probe

function Invoke-AskwellProbe {
    Write-AskwellSay 'Probing this machine''s hardware...'
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $python) {
        Write-AskwellSay 'No Python found on PATH; Askwell will fall back to the standard profile on first launch.'
        return
    }
    $env:ASKWELL_PROBE_RESULT_PATH = Join-Path $DataDir 'probe.json'
    & $python.Source (Join-Path $InstallPrefix 'askwell-probe')
    if ($LASTEXITCODE -ne 0) {
        Write-AskwellSay 'Probe did not complete; Askwell will fall back to the standard profile on first launch.'
    }
}

# ---------------------------------------------------------------- 8. start menu + session start

function Register-AskwellShortcuts {
    $shellDest = Join-Path $InstallPrefix 'askwell-shell.exe'
    $wshShell = New-Object -ComObject WScript.Shell

    $startMenuShortcut = $wshShell.CreateShortcut((Join-Path $StartMenuDir 'Askwell.lnk'))
    $startMenuShortcut.TargetPath = $shellDest
    $startMenuShortcut.Description = 'Ask questions of your own files and databases, locally'
    $startMenuShortcut.Save()
    Write-AskwellSay "Start-menu entry installed: $(Join-Path $StartMenuDir 'Askwell.lnk')"

    New-Item -ItemType Directory -Force -Path $StartupDir | Out-Null
    $startupShortcut = $wshShell.CreateShortcut((Join-Path $StartupDir 'Askwell.lnk'))
    $startupShortcut.TargetPath = $shellDest
    $startupShortcut.Save()
    Write-AskwellSay 'Askwell registered to start with your session (Startup folder).'
}

# The platform half of M7-PACK-DEPLOY-142: the stack and native inference
# process, each as their own Scheduled Task triggered `AtLogOn`, running for
# the session whether or not the app itself is ever opened.
#
# `-ExecutionTimeLimit ([TimeSpan]::Zero)` matters more here than it looks:
# Task Scheduler's own default execution time limit is 72 hours, after which
# it stops a still-running task outright — exactly wrong for something meant
# to run for the entire session. Zero is documented to mean "no time limit".
#
# `-MultipleInstances IgnoreNew` is the "starting Askwell twice attaches
# rather than creating a duplicate stack" edge case: a second attempt to
# start an already-running task is a no-op rather than a second `podman
# compose up`.
#
# Verification gap, disclosed rather than assumed away (issue #606,
# re-confirmed in docs/decisions.md this date): this build host has no pwsh
# (PowerShell 7) and no passwordless sudo to install one, so
# `Register-ScheduledTask`/`RestartCount`/`RestartInterval`'s exact restart
# semantics — in particular whether a non-zero *action process* exit counts
# as the "task failure" that triggers a restart, versus only a failure Task
# Scheduler itself judges at the task level — were verified against
# documentation, not a live Windows session. If that assumption is wrong,
# the backoff-and-restart acceptance criterion is unmet on Windows
# specifically, silently. Issue #606 stays open, re-owned rather than
# silently assumed correct, until a Windows host or a Linux host with pwsh
# installed can run the real walkthrough this ticket's own Testing Notes
# describe.
function Register-AskwellStackTask {
    $podman = Get-Command podman -ErrorAction SilentlyContinue
    if (-not $podman) {
        Write-AskwellSay 'Podman not found on PATH; cannot register the stack scheduled task.'
        return
    }
    $taskName = Get-AskwellStackTaskName
    $taskArgs = Get-AskwellStackTaskArguments -ComposePath (Join-Path $InstallPrefix 'compose.yaml') -EnvPath (Join-Path $InstallPrefix '.env')
    $action = New-ScheduledTaskAction -Execute $podman.Source -Argument $taskArgs -WorkingDirectory $InstallPrefix
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Askwell container stack' | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-AskwellSay "Askwell's container stack registered to run with your session (Scheduled Task: $taskName)."
}

function Register-AskwellInferenceTask {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
    if (-not $python) {
        Write-AskwellSay 'No Python found on PATH; cannot register the inference scheduled task.'
        return
    }
    $taskName = Get-AskwellInferenceTaskName
    $taskArgs = Get-AskwellInferenceTaskArguments -ScriptPath (Join-Path $InstallPrefix 'askwell-inference')
    $action = New-ScheduledTaskAction -Execute $python.Source -Argument $taskArgs -WorkingDirectory $InstallPrefix
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Askwell native inference supervisor' | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-AskwellSay "Askwell's native inference process registered to run with your session (Scheduled Task: $taskName)."
}

function Register-AskwellUninstallEntry {
    $uninstallCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Here\uninstall.ps1`""
    $values = Get-AskwellUninstallRegistryValues -Version $Version -UninstallCommand $uninstallCmd -InstallPrefix $InstallPrefix
    $keyPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Askwell'
    New-Item -Path $keyPath -Force | Out-Null
    foreach ($name in $values.Keys) {
        New-ItemProperty -Path $keyPath -Name $name -Value $values[$name] -Force | Out-Null
    }
}

# ---------------------------------------------------------------- 9. install record + launch

function Write-AskwellRecord {
    $method = if (Test-AskwellPreviousInstall $DataDir) { 'upgrade' } else { 'install' }
    Write-AskwellInstallRecord -DataDir $DataDir -Version $Version -Method $method
    Write-AskwellSay "Install record written: $(Get-AskwellInstallRecordPath $DataDir)"
}

function Start-Askwell {
    Write-AskwellSay 'Starting Askwell...'
    Start-Process -FilePath (Join-Path $InstallPrefix 'askwell-shell.exe') -WorkingDirectory $InstallPrefix
    Write-AskwellSay 'Askwell is starting. Its window will open shortly.'
}

function Main {
    Write-AskwellSay "Installing Askwell $Version"
    Test-AskwellRuntime
    Test-AskwellDiskSpace
    Test-AskwellPrevious
    Test-AskwellArtefacts
    Copy-AskwellFiles
    New-AskwellDataDirs
    Invoke-AskwellProbe
    Register-AskwellShortcuts
    Register-AskwellStackTask
    Register-AskwellInferenceTask
    Register-AskwellUninstallEntry
    Write-AskwellRecord
    Start-Askwell
    Write-AskwellSay 'Done. Askwell is also available any time from your Start menu.'
}

Main
