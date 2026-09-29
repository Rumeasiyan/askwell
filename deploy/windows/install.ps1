<#
.SYNOPSIS
    Askwell's Windows installer. M7-PACK-DEPLOY-140.

.DESCRIPTION
    Checks virtualisation and Podman, places the stack, the native inference
    supervisor, the probe and the desktop shell, creates the data
    directories, registers Askwell to start with the session, and opens the
    Askwell window - never a browser tab. Mirrors deploy/linux/install.sh's
    shape; see that file's header for the artefact layout both installers
    share and issue #559 for the one artefact neither builds itself.

    What this script needs beside itself, and where it expects to find it:

      REPO_ROOT (two directories above this script)\
        compose.yaml, .env.example, deploy\postgres, deploy\sandbox, deploy\redis - the stack
        deploy\probe\askwell-probe                                    - the host probe
        deploy\inference\askwell-inference                             - native inference (a
                                                                          standard-library-only
                                                                          Python script; needs a
                                                                          Python on this host's
                                                                          PATH, same as Linux)
        deploy\inference\llama.cpp\{gpu,cpu}\                          - llama.cpp's Vulkan and
                                                                          CPU builds (a release
                                                                          only; M10-FIX-DEPLOY-222)
        web\src-tauri\target\release\askwell-shell.exe                  - the desktop shell
        web\out\                                                        - the built interface
                                                                          compose.yaml mounts (#766)
        images\*.tar                                                    - the container images,
                                                                          saved (optional)

    A release zip ships this layout, assembled by scripts/release-artefact.sh
    in .github/workflows/release.yml (M9-REL-DEPLOY-214). `images\` is what
    a release adds that a source checkout lacks, so nothing is built from
    source or pulled here.

    Podman on Windows only runs containers inside a WSL2 virtual machine -
    there is no native Windows container runtime - so this checks
    virtualisation before Podman, and names the firmware setting to enable
    when it is off, since that is a BIOS/UEFI change no installer running
    inside Windows can make for the user.

    Never fetches a model. `winget`/Podman's own install may need the network
    to install or to pull container images - the same class of install-time
    exception `scripts/dev.sh lock`/`web-install` already name (AGENTS.md
    section 5) - but nothing here ever reaches out for model weights.
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
            "or 'SVM Mode', enable it, save and reboot. Askwell cannot enable this itself - it " +
            "is a firmware setting, not a Windows one - then run this installer again.")
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

# ---------------------------------------------------------------- 1a. compose provider

# Issue #767: `podman compose` runs an external provider, and docker-compose
# is the one this stack is verified with. Refused by name before anything is
# copied. Not installed from here: winget does not refresh this session's
# PATH, so a provider installed now would still not be found until the next.
function Test-AskwellComposeProvider {
    $reported = Get-AskwellComposeVersionText
    if (Test-AskwellComposeMeetsMinimum $reported) {
        Write-AskwellSay "Compose provider found: Docker Compose $(ConvertFrom-AskwellComposeVersion $reported)"
        return
    }
    $found = 'none'
    if ($reported) { $found = ($reported -split "`n")[0] }
    Write-AskwellDie ("Askwell runs its containers through 'podman compose', which needs Docker Compose " +
        "$script:AskwellMinComposeVersion or newer installed as its provider (podman-compose is not supported). " +
        "Found: $found. Install it with: winget install -e --id Docker.DockerCompose - then open a new " +
        "PowerShell and run this installer again. Nothing has been copied.")
    exit 1
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
        Write-AskwellDie "Not enough disk space at $InstallPrefix`: need $(Format-AskwellBytes $needed), have $(Format-AskwellBytes $have). Free up space and run this installer again - nothing has been copied."
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
    $webIndex = Join-Path $RepoRoot 'web\out\index.html'
    if (-not (Test-Path $webIndex)) {
        Write-AskwellSay "Missing: $webIndex"
        Write-AskwellSay '  The interface has not been built. Build it first with: scripts/dev.sh web-build'
        $missing = $true
    }
    if ($missing) {
        Write-AskwellDie 'One or more required files are missing (listed above). This installer places what a release build produces; it does not build them. Nothing has been copied.'
        exit 1
    }

    # Windows' legacy MAX_PATH (260) fails a plain file open unless the
    # caller opts into \\?\ - checked against the destination path this
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
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallPrefix 'deploy\redis') | Out-Null

    Copy-Item (Join-Path $RepoRoot 'compose.yaml') (Join-Path $InstallPrefix 'compose.yaml') -Force

    $envFile = Join-Path $InstallPrefix '.env'
    $keptEnv = Get-AskwellKeptEnvPath $DataDir
    if (-not (Test-Path $envFile) -and (Test-Path $keptEnv)) {
        # Issue #765: the database volumes outlived a plain uninstall, and
        # these are the passwords they were initialised with.
        Move-Item $keptEnv $envFile
        Write-AskwellSay 'Restored the database credentials the previous uninstall kept, so this install opens the database it left in place.'
    } elseif (-not (Test-Path $envFile)) {
        Copy-Item (Join-Path $RepoRoot '.env.example') $envFile
        Set-AskwellEnvPasswords $envFile
        Write-AskwellSay "Generated database credentials in $envFile"
    }
    # Every run, not only a fresh one: an upgrade from before Redis had users
    # needs these generated too, or the stack refuses to start.
    Set-AskwellRedisPasswords $envFile

    Copy-Item (Join-Path $RepoRoot 'deploy\postgres\*') (Join-Path $InstallPrefix 'deploy\postgres\') -Recurse -Force
    Copy-Item (Join-Path $RepoRoot 'deploy\sandbox\*') (Join-Path $InstallPrefix 'deploy\sandbox\') -Recurse -Force
    Copy-Item (Join-Path $RepoRoot 'deploy\redis\*') (Join-Path $InstallPrefix 'deploy\redis\') -Recurse -Force

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
    Copy-AskwellLlamaCpp

    # Replaced, not merged: a file an older interface had and this one does
    # not must not keep being served.
    $webDest = Join-Path $InstallPrefix 'web\out'
    if (Test-Path $webDest) { Remove-Item $webDest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallPrefix 'web') | Out-Null
    Copy-Item (Join-Path $RepoRoot 'web\out') $webDest -Recurse -Force

    $shellDest = Join-Path $InstallPrefix 'askwell-shell.exe'
    Copy-Item $ShellBin $shellDest -Force
    if (-not (Test-Path $shellDest)) {
        Write-AskwellDie (Get-AskwellQuarantineMessage 'askwell-shell.exe')
        exit 1
    }

    Write-AskwellSay "Application files placed under $InstallPrefix"
}

# The llama.cpp builds a release carries (M10-FIX-DEPLOY-222), placed next to
# askwell-inference, which is where it looks. Both go: the supervisor asks
# the Vulkan build at each start whether there is a graphics device it can
# use and runs the CPU build when there is not. Replaced, not merged, as on
# Linux. Windows will not replace a DLL a running process has loaded, so an
# upgrade stops the inference task and any llama-server started from this
# folder first; Register-AskwellInferenceTask starts it again. A source
# checkout carries none, and the supervisor runs llama-server from PATH.
function Copy-AskwellLlamaCpp {
    $src = Join-Path $RepoRoot 'deploy\inference\llama.cpp'
    if (-not (Test-Path (Join-Path $src 'gpu\llama-server.exe')) -and
        -not (Test-Path (Join-Path $src 'cpu\llama-server.exe'))) {
        Write-AskwellSay 'No llama.cpp build is bundled here; Askwell will run llama-server from PATH.'
        return
    }
    $dest = Join-Path $InstallPrefix 'llama.cpp'
    if (Test-Path $dest) {
        Stop-AskwellLlamaCpp -Dir $dest
        Remove-Item $dest -Recurse -Force
    }
    Copy-Item $src $dest -Recurse -Force
    if ((Test-Path (Join-Path $src 'gpu\llama-server.exe')) -and
        -not (Test-Path (Join-Path $dest 'gpu\llama-server.exe'))) {
        Write-AskwellDie (Get-AskwellQuarantineMessage 'llama-server.exe')
        exit 1
    }
    Write-AskwellSay "llama.cpp placed under $dest. Answers run on the graphics card where llama.cpp can use it, and on the processor otherwise."
}

# ---------------------------------------------------------------- 5a. container images

# Before the stack task is registered: `up` uses an image already present
# and builds or pulls only one that is missing. This needs a running Podman
# machine, which this installer does not create (issue #808), so a failure
# names that cause as well as a damaged download.
function Import-AskwellImages {
    $archives = Get-AskwellBundledImages $RepoRoot
    if ($archives.Count -eq 0) {
        Write-AskwellSay 'No bundled container images; the stack will use the images already on this machine.'
        return
    }
    foreach ($archive in $archives) {
        Write-AskwellSay "Loading container image $(Split-Path -Leaf $archive)..."
        & podman load -q -i $archive | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-AskwellDie ("Could not load the container image $archive. Check that Podman's machine " +
                "is running (podman machine init, then podman machine start), and that the download " +
                "matches SHA256SUMS (docs/installing.md), then run this installer again.")
            exit 1
        }
    }
    Write-AskwellSay 'Container images loaded.'
}

# ---------------------------------------------------------------- 6. data dirs

function New-AskwellDataDirs {
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $DataDir 'models') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $DataDir 'logs') | Out-Null
    $models = Get-AskwellModelsDir $env:USERPROFILE
    New-Item -ItemType Directory -Force -Path $models | Out-Null
    Write-AskwellSay "Data directory: $DataDir"
    Write-AskwellSay "Models directory: $models"
}

# ---------------------------------------------------------------- 6a. stop the old version

# Issue #768: on an upgrade the old version's containers are still serving.
# They stop before the schema moves, and Register-AskwellStackTask starts the
# new ones after. Stopping the task ends `podman compose up` without always
# stopping its containers, so `down` follows. Only on an upgrade.
function Stop-AskwellPreviousStack {
    if (-not (Test-AskwellPreviousInstall $DataDir)) { return }
    $podman = Get-Command podman -ErrorAction SilentlyContinue
    if (-not $podman) {
        Write-AskwellDie 'Podman is not on PATH, so the running Askwell could not be stopped before its database is upgraded. The install stopped at this step and is not complete.'
        exit 1
    }
    Stop-ScheduledTask -TaskName (Get-AskwellStackTaskName) -ErrorAction SilentlyContinue
    $code = Stop-AskwellStackContainers -Podman $podman.Source -ComposePath (Join-Path $InstallPrefix 'compose.yaml') `
        -EnvPath (Join-Path $InstallPrefix '.env')
    if ($code -ne 0) {
        Write-AskwellDie "Could not stop the running Askwell's containers (podman compose down exited $code), so the upgrade stopped before changing the database. The new application files are in place; run this installer again."
        exit 1
    }
    Write-AskwellSay 'Stopped the running Askwell so its database can be upgraded; the new version starts once the upgrade is done.'
}

# ---------------------------------------------------------------- 6b. database schema

# Issue #698: nothing used to run a migration, so a fresh install had no
# schema and an upgrade ran new code against the old one. Runs before the
# stack task is registered, so a failure stops the install here, named.
function Invoke-AskwellDatabaseMigration {
    $podman = Get-Command podman -ErrorAction SilentlyContinue
    if (-not $podman) {
        Write-AskwellDie 'Podman is not on PATH, so the database could not be brought up to date. The install stopped at this step and is not complete.'
        exit 1
    }
    $log = Join-Path $DataDir 'logs\migrate.log'
    Write-AskwellSay 'Bringing Askwell''s database up to date (the first run also starts the database)...'
    $code = Invoke-AskwellMigration -Podman $podman.Source -ComposePath (Join-Path $InstallPrefix 'compose.yaml') `
        -EnvPath (Join-Path $InstallPrefix '.env') -LogPath $log
    if ($code -ne 0) {
        if (Test-Path $log) { Get-Content $log -Tail 20 | ForEach-Object { Write-Host $_ } }
        Write-AskwellDie ("The database migration (alembic upgrade head, run as the stack's migrate service) " +
            "failed with exit status $code (its last lines are above, the full output is in $log). The install " +
            "stopped at this step and is not complete: nothing after it was done. The upgrade runs as one " +
            "transaction, so the database is left as it was before this step. Run this installer again once " +
            "the cause is fixed.")
        exit 1
    }
    $applied = Get-AskwellMigrationsApplied $log
    if ($applied -eq 0) {
        Write-AskwellSay 'Database schema already up to date; no migrations to apply.'
    } else {
        Write-AskwellSay "Database schema up to date: applied $applied migration(s)."
    }
}

# ---------------------------------------------------------------- 7. probe

function Invoke-AskwellProbe {
    Write-AskwellSay 'Probing this machine''s hardware...'
    $python = Get-AskwellPython
    if (-not $python) {
        Write-AskwellSay 'No Python found on PATH; Askwell will fall back to the standard profile on first launch.'
        return
    }
    $env:ASKWELL_PROBE_RESULT_PATH = Join-Path $DataDir 'probe.json'
    & $python (Join-Path $InstallPrefix 'askwell-probe')
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
# it stops a still-running task outright - exactly wrong for something meant
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
# semantics - in particular whether a non-zero *action process* exit counts
# as the "task failure" that triggers a restart, versus only a failure Task
# Scheduler itself judges at the task level - were verified against
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
    $python = Get-AskwellPython
    if (-not $python) {
        Write-AskwellSay 'No Python found on PATH; cannot register the inference scheduled task.'
        return
    }
    $taskName = Get-AskwellInferenceTaskName
    $taskArgs = Get-AskwellInferenceTaskArguments -ScriptPath (Join-Path $InstallPrefix 'askwell-inference')
    $action = New-ScheduledTaskAction -Execute (Get-AskwellWindowlessPython $python) -Argument $taskArgs -WorkingDirectory $InstallPrefix
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
    Test-AskwellComposeProvider
    Test-AskwellDiskSpace
    Test-AskwellPrevious
    Test-AskwellArtefacts
    Copy-AskwellFiles
    Import-AskwellImages
    New-AskwellDataDirs
    Stop-AskwellPreviousStack
    Invoke-AskwellDatabaseMigration
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
