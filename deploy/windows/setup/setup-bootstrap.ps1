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

    What it cannot do in one pass:
      - turn on CPU virtualisation, which is a firmware setting;
      - finish enabling WSL, which needs Windows to restart. Everything else
        is installed first. Then it copies itself to %ProgramData%\AskwellSetup,
        asks Windows to run it once at the next sign-in (RunOnce), and exits
        with 30; the setup exe offers to restart. After the restart it runs
        again with -Resume, finishes the install and opens Askwell. One
        restart, and nothing to run by hand.

    Exit codes read by the setup exe:
       0  installed
      20  winget (App Installer) is missing
      21  Podman could not be installed
      22  Docker Compose could not be installed
      23  Setup's own files did not load (lib.ps1 failed to parse)
      24  running as 32-bit PowerShell, which cannot see wsl.exe
      30  WSL was just enabled; Windows must restart, and Setup continues
          by itself after the next sign-in
      31  the Podman machine could not be started
      32  WSL could not be enabled
      33  WSL still waits for a restart after Setup's own restart
      anything else: install.ps1's own exit code, its reason already printed
#>
param(
    # The unpacked release tree. Defaults to this script's own tree, which is
    # how the resumed run finds it (see Get-AskwellResumeCommand).
    [string]$Root = (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))),
    # Set only on the run Windows starts after the restart.
    [switch]$Resume
)

$ErrorActionPreference = 'Continue'
$RunOnceKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce'
# wsl.exe writes UTF-16 unless told otherwise, which prints as spaced-out
# text in Setup's log.
$env:WSL_UTF8 = '1'

# install.ps1's own helpers, so every check here is the one it will make.
. (Join-Path $Root 'deploy\windows\lib.ps1')

# Everything Setup prints also goes to this log, which a failed run turns
# into the report on the Desktop. Appended, not replaced, so a report after
# the restart also carries what the first run did.
$SetupLog = Join-Path $env:TEMP 'AskwellSetup.log'

function Say([string]$Text) {
    Write-Output $Text
    try { [System.IO.File]::AppendAllText($SetupLog, "$Text`r`n") } catch { }
}

function Get-Fact([scriptblock]$Read) {
    # One line of the report. A fact that cannot be read says so; it never
    # stops the report from being written.
    try {
        $value = (& $Read | Out-String).Trim() -replace '\s*\r?\n\s*', '; '
        if ($value) { return $value }
        return 'none'
    } catch {
        return 'unknown'
    }
}

function Save-SetupReport([int]$Code) {
    # Written on every failure, opened in Notepad, and never sent anywhere:
    # the person sends the file themselves (docs/decisions.md, 2026-09-29).
    try {
        $log = ''
        if (Test-Path $SetupLog) { $log = [System.IO.File]::ReadAllText($SetupLog) }
        $name = 'Askwell-Setup-report-{0}.txt' -f (Get-Date -Format 'yyyyMMdd-HHmm')
        $desktop = [Environment]::GetFolderPath('Desktop')
        if (-not $desktop -or -not (Test-Path $desktop)) { $desktop = $env:TEMP }
        $path = Join-Path $desktop $name
        if (Get-Command Format-AskwellSetupReport -ErrorAction SilentlyContinue) {
            $facts = [ordered]@{
                'Askwell version'          = Get-Fact { Get-Content (Join-Path $Root 'VERSION') -Raw }
                'Setup run'                = $(if ($Resume) { 'after the restart' } else { 'first run' })
                'Windows'                  = Get-Fact { $os = Get-CimInstance Win32_OperatingSystem; "$($os.Caption) $($os.Version) build $($os.BuildNumber) $($os.OSArchitecture)" }
                'Memory'                   = Get-Fact { '{0:N1} GB' -f ((Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize / 1MB) }
                'CPU'                      = Get-Fact { (Get-CimInstance Win32_Processor | Select-Object -First 1).Name }
                'Virtualisation in firmware' = Get-Fact { (Get-CimInstance Win32_Processor | Select-Object -First 1).VirtualizationFirmwareEnabled }
                '64-bit PowerShell'        = [Environment]::Is64BitProcess
                'Virtual Machine Platform' = Get-Fact { Get-VmPlatformState }
                'Podman'                   = Get-Fact { & podman --version }
                'Compose'                  = Get-Fact { Get-AskwellComposeVersionText }
                'WSL'                      = Get-Fact { & wsl.exe --version }
                'Time (UTC)'               = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')
            }
            $protect = { param($t) Protect-AskwellReportText -Text $t -UserProfile $env:USERPROFILE -UserName $env:USERNAME -ComputerName $env:COMPUTERNAME }
            foreach ($key in @($facts.Keys)) { $facts[$key] = & $protect "$($facts[$key])" }
            $text = Format-AskwellSetupReport -Code $Code -Facts $facts -Log (& $protect $log)
        } else {
            # lib.ps1 did not load (code 23): the raw log is still worth sending.
            $text = "Askwell Setup report (code $Code). Please send this file to whoever gave you Askwell.`r`n`r`n$log"
        }
        [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding $false))
        Write-Output ''
        Write-Output "Setup saved a report on your Desktop: $name"
        Write-Output 'Please send that file to whoever gave you Askwell. It tells them what went wrong.'
        Start-Process -FilePath "$env:SystemRoot\System32\notepad.exe" -ArgumentList "`"$path`"" -ErrorAction SilentlyContinue
    } catch {
        Write-Output "Setup could not save its report: $($_.Exception.Message)"
    }
}

function Stop-Setup([int]$Code) {
    Save-SetupReport $Code
    # After the restart this script runs in its own window, which would close
    # the moment it exits, taking the reason with it.
    if ($Resume) {
        Say "Askwell Setup did not finish (code $Code). Once the above is fixed, run Askwell-Setup.exe again."
        Read-Host 'Press Enter to close this window' | Out-Null
    }
    exit $Code
}

Say ("=== Askwell Setup started {0} UTC{1}" -f (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm'), $(if ($Resume) { ', after the restart' } else { '' }))

# With ErrorActionPreference 'Continue', a lib.ps1 that fails to parse leaves
# its functions undefined and every check below quietly answers "missing":
# 0.9.2 reported "Docker Compose did not install" right after it had. Stop
# here instead, with the real reason.
if (-not (Get-Command Test-AskwellComposeMeetsMinimum -ErrorAction SilentlyContinue)) {
    Say "Askwell Setup's own files did not load (deploy\windows\lib.ps1). This is a fault in Setup, not in your PC. Please report it: https://github.com/Rumeasiyan/askwell/issues"
    Stop-Setup 23
}

# A 32-bit PowerShell on 64-bit Windows is redirected from System32 to
# SysWOW64, where wsl.exe does not exist, so WSL would look absent on every
# PC. The setup exe launches the 64-bit one; this catches anything that
# does not.
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    Say "Askwell Setup is running as 32-bit PowerShell, which cannot see the Windows Subsystem for Linux. This is a fault in Setup, not in your PC. Please report it: https://github.com/Rumeasiyan/askwell/issues"
    Stop-Setup 24
}

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
    #
    # 0.9.6 still stopped with 22 on every new PC: it asked `podman compose
    # version`, which needs Podman's machine, and the machine is created only
    # after this check. Get-AskwellComposeVersionText asks docker-compose.
    return [bool](Test-AskwellComposeMeetsMinimum (Get-AskwellComposeVersionText))
}

function Get-VmPlatformState {
    # "" when it cannot be read, which Get-AskwellWslState treats as missing.
    try {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -ErrorAction Stop
        return "$($feature.State)"
    } catch {
        return ''
    }
}

function Register-AskwellResume {
    # Copy the release tree out of %TEMP% (the exe deletes it when it closes)
    # and have Windows run this script once at the next sign-in. HKLM RunOnce
    # runs elevated for an administrator, and Windows deletes the entry before
    # running it, so it can never repeat on its own.
    $stage = Get-AskwellSetupStageDir $env:ProgramData
    if ((Resolve-Path $Root).Path.TrimEnd('\') -ne $stage.TrimEnd('\')) {
        Say "Keeping Setup's files so it can continue after the restart..."
        if (Test-Path $stage) { Remove-Item -Path $stage -Recurse -Force -ErrorAction SilentlyContinue }
        New-Item -ItemType Directory -Force -Path $stage | Out-Null
        Copy-Item -Path (Join-Path $Root '*') -Destination $stage -Recurse -Force
    }
    $command = Get-AskwellResumeCommand $env:SystemRoot $stage
    # Never New-Item -Force on an existing key: for the registry it replaces
    # the key, deleting every other program's pending RunOnce entry.
    if (-not (Test-Path $RunOnceKey)) { New-Item -Path $RunOnceKey | Out-Null }
    Set-ItemProperty -Path $RunOnceKey -Name 'AskwellSetup' -Value $command
}

function Remove-AskwellStage {
    # The continuation is running from the stage, so it cannot delete itself;
    # a detached cmd does it a few seconds after this process has exited.
    $stage = Get-AskwellSetupStageDir $env:ProgramData
    if (Test-Path $stage) {
        Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -WindowStyle Hidden `
            -ArgumentList "/c timeout /t 10 /nobreak >nul & rmdir /s /q `"$stage`""
    }
}

function Test-WslAnswers {
    # `wsl --version` exists only in the WSL that winget and the Store
    # install; the in-box stub answers it with an error. So it is the test
    # that WSL is actually installed, not just its launcher.
    & wsl.exe --version *> $null
    return ($LASTEXITCODE -eq 0)
}

function Install-Wsl {
    # See $AskwellWslMsiUrl in lib.ps1 for why it is this and not winget.
    $msi = Join-Path $env:TEMP ("wsl.$AskwellWslMsiVersion.x64.msi")
    $have = (Test-Path $msi) -and ((Get-FileHash -Algorithm SHA256 -Path $msi).Hash -eq $AskwellWslMsiSha256)
    if (-not $have) {
        Say "Downloading the Windows Subsystem for Linux $AskwellWslMsiVersion from Microsoft (about 250 MB)..."
        try {
            # Windows PowerShell 5.1 needs TLS 1.2 asked for, and draws a
            # progress bar so slowly that it makes a large download crawl.
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -UseBasicParsing -Uri $AskwellWslMsiUrl -OutFile $msi -ErrorAction Stop
        } catch {
            Say "  The download failed: $($_.Exception.Message)"
            return
        }
        $hash = (Get-FileHash -Algorithm SHA256 -Path $msi).Hash
        if ($hash -ne $AskwellWslMsiSha256) {
            Say "  The download does not match Microsoft's published checksum (got $hash), so it was not run."
            Remove-Item -Path $msi -Force -ErrorAction SilentlyContinue
            return
        }
        Say "  Downloaded and checked."
    }
    Say "Installing the Windows Subsystem for Linux..."
    $msiLog = Join-Path $env:TEMP 'AskwellSetup-wsl-msi.log'
    $process = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -Wait -PassThru `
        -ArgumentList "/i `"$msi`" /quiet /norestart /log `"$msiLog`""
    $code = if ($process) { $process.ExitCode } else { -1 }
    if (Test-AskwellMsiSucceeded $code) {
        Say "  Installed (Windows Installer code $code)."
    } else {
        Say "  Windows Installer stopped with code $code. Its log: $msiLog"
    }
}

function Install-WithWinget([string]$Id, [string]$Label) {
    Say "Installing $Label. This can take a few minutes..."
    # --disable-interactivity: no progress bars, which reached the log and the
    # report as lines of garbled block characters.
    & winget install -e --id $Id --silent --disable-interactivity --accept-source-agreements --accept-package-agreements 2>&1 |
        ForEach-Object { Say "  $_" }
    Update-AskwellPath
}

if ($Resume) {
    # The run Windows starts after the restart. HKLM RunOnce should already
    # be elevated; if it is not, ask once rather than fail on the first
    # install step.
    $principal = New-Object System.Security.Principal.WindowsPrincipal([System.Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Verb RunAs `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Resume"
        exit 0
    }
    $Host.UI.RawUI.WindowTitle = 'Askwell Setup - finishing the install'
    Say "Askwell Setup is continuing after the restart."
}

Say "Askwell setup is checking this PC."
Update-AskwellPath

if (-not (Test-Command 'winget')) {
    Say ("Windows' App Installer (winget) is missing. Install 'App Installer' from the " +
        "Microsoft Store, then run Askwell Setup again.")
    Stop-Setup 20
}

if (-not (Test-Command 'podman')) {
    Install-WithWinget 'RedHat.Podman' 'Podman (runs Askwell''s local services)'
    if (-not (Test-Command 'podman')) {
        Say "Podman did not install. The messages above say why. Run Askwell Setup again once that is fixed."
        Stop-Setup 21
    }
}
Say "Podman: $((& podman --version) -join ' ')"

if (-not (Test-ComposeProvider)) {
    Install-WithWinget 'Docker.DockerCompose' 'Docker Compose (starts Askwell''s services)'
    if (-not (Test-ComposeProvider)) {
        Say "Docker Compose did not install. The messages above say why. Run Askwell Setup again once that is fixed."
        Stop-Setup 22
    }
}
Say "Compose provider: $(Get-AskwellComposeVersionText)"

# WSL is what Podman's machine runs in, and it comes last among the
# prerequisites because it is the one that can need a restart: everything
# that can be installed before it has been.
#
# Two parts, both done without `wsl.exe --install`: Windows' in-box wsl.exe
# refuses to install anything when it has no console ("The Windows Subsystem
# for Linux is not installed. You can install by running 'wsl.exe
# --install'", exit 1), and the setup exe always runs this script without
# one. Found on the Windows test VM, 0.9.6. Instead:
#   - the Virtual Machine Platform, a Windows feature, is turned on with
#     Enable-WindowsOptionalFeature, which needs no console;
#   - WSL itself is installed from winget (Microsoft.WSL, MIT), like Podman.
# Proven on the VM: after these and one restart, `podman machine init` and
# `start` succeed.
$enabledThisRun = $false
if ((Get-AskwellWslState (Get-VmPlatformState)) -eq 'missing') {
    Say "Enabling the Virtual Machine Platform, which the Windows Subsystem for Linux needs..."
    try {
        $result = Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart -ErrorAction Stop
        Say "  Enabled. Windows restart needed: $($result.RestartNeeded)"
    } catch {
        Say "  $($_.Exception.Message)"
    }
    $enabledThisRun = $true
}
if (-not (Test-WslAnswers)) {
    Install-Wsl
    if (-not (Test-WslAnswers)) {
        Say "The Windows Subsystem for Linux did not install. The messages above say why. Run Askwell Setup again once that is fixed."
        Stop-Setup 32
    }
    $enabledThisRun = $true
}
$state = Get-AskwellWslState (Get-VmPlatformState) -EnabledThisRun:$enabledThisRun
if ($state -eq 'missing') {
    Say ("The Virtual Machine Platform could not be enabled. The messages above say why. " +
        "If they mention virtualisation, turn on Intel VT-x / AMD-V in this PC's firmware (BIOS/UEFI) setup, then run Askwell Setup again.")
    Stop-Setup 32
}
if ($state -eq 'restart') {
    if ($Resume) {
        # Windows clears EnablePending on restart, so this should not happen;
        # if it does, a second automatic restart would not help either.
        Say ("Windows still reports WSL as waiting for a restart, after the restart Setup asked for. " +
            "Restart once more, then run Askwell Setup again. If this repeats, please report it: https://github.com/Rumeasiyan/askwell/issues")
        Stop-Setup 33
    }
    Register-AskwellResume
    Say "Windows needs to restart once to finish enabling WSL. Setup will continue by itself after you sign in again."
    exit 30
}

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
    Stop-Setup 31
}

Say "Everything Askwell needs is in place. Installing Askwell..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'deploy\windows\install.ps1') -Yes 2>&1 |
    ForEach-Object { Say $_ }
$code = $LASTEXITCODE
if ($code -eq 0) {
    Remove-Item -Path $SetupLog -Force -ErrorAction SilentlyContinue
} else {
    Save-SetupReport $code
}
if ($Resume) {
    # This window is the only place the resumed run can show anything.
    if ($code -eq 0) {
        Remove-AskwellStage
        Say "Askwell is installed and opening. This window closes in 15 seconds."
        Start-Sleep -Seconds 15
    } else {
        Say "Askwell did not finish installing (code $code). The reason is above, and in the report Setup saved on your Desktop."
        Read-Host 'Press Enter to close this window' | Out-Null
    }
}
exit $code
