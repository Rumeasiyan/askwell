# Runs the real setup-bootstrap.ps1 end to end, with the Windows tools it
# drives replaced by fakes: winget, podman, wsl.exe, the Windows feature
# query, the RunOnce registry write, Start-Process and the prompts.
#
# Each scenario is a path a real PC took or can take. The restart loop in
# 0.9.3 is here as "after the restart": WSL enabled, no Linux distribution,
# and `wsl --status` failing, which is exactly what that release tripped on.
#
# Runs under Windows PowerShell 5.1 on a Windows runner (.github/workflows/
# windows.yml) and under pwsh anywhere. Never touches the real registry,
# never installs anything. What it cannot cover is a real restart and a real
# WSL; that is the Windows VM's job (#836).
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tree = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $Here))
$Boot = Join-Path $Here 'setup-bootstrap.ps1'

$Scratch = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid())
$env:TEMP = Join-Path $Scratch 'temp'
$env:ProgramData = Join-Path $Scratch 'programdata'
$env:USERNAME = 'nimal.perera'
$env:USERPROFILE = $Scratch
$env:COMPUTERNAME = 'NIMAL-LAPTOP'
New-Item -ItemType Directory -Force -Path $env:TEMP, $env:ProgramData | Out-Null
$Stage = Join-Path $env:ProgramData 'AskwellSetup'
$WslConfigPath = Join-Path $env:USERPROFILE '.wslconfig'
# Where Setup looks for the Visual C++ runtime. The Windows runner has a real
# one, so each scenario gets its own System32, and SystemRoot points at it
# only while the scenario runs. Everything else Setup reaches through
# SystemRoot is faked.
$RealSystemRoot = $env:SystemRoot
$FakeSystemRoot = Join-Path $Scratch 'windows'
$global:FakeSystem32 = Join-Path $FakeSystemRoot 'System32'
New-Item -ItemType Directory -Force -Path $FakeSystem32 | Out-Null
$Desktop = [Environment]::GetFolderPath('Desktop')
if (-not $Desktop -or -not (Test-Path $Desktop)) { $Desktop = $env:TEMP }

# In Windows PowerShell 5.1 Get-FileHash is a function in a module that
# loads on first use, and loading it replaces a fake defined before it:
# on the Windows runner the real hash of the fake download was taken. Load
# it now, so the fakes below are the ones that stay.
Import-Module Microsoft.PowerShell.Utility -ErrorAction SilentlyContinue
Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue
# The Visual C++ runtime's installer: what Windows says about its signature.
function global:Get-AuthenticodeSignature {
    param($FilePath)
    $subject = $(if ($global:VcSignedBy) { $global:VcSignedBy } else { $null })
    [pscustomobject]@{
        Status = $global:VcSignatureStatus
        SignerCertificate = $(if ($subject) { [pscustomobject]@{ Subject = $subject } } else { $null })
    }
}
function global:winget { $global:LASTEXITCODE = 0 }
# The WSL installer: a download, its checksum, and msiexec.
function global:Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing, $ErrorAction)
    $global:Downloads += , $Uri
    Set-Content -Path $OutFile -Value 'msi'
}
function global:Get-FileHash {
    param($Algorithm, $Path)
    $hash = if (-not $global:DownloadMatches) { 'BAD' }
        elseif ("$Path" -match 'python') { 'EDEC09C4853AEAE9AC36EFB8C9F95B6B8E2FEE65EEE56D9767A8B7C69C574403' }
        else { 'A3505A50F4CC585551D11D9DE824BA4375448D7A68F2E71D3FB315FA986FC754' }
    [pscustomobject]@{ Hash = $hash }
}
function global:docker-compose { $global:LASTEXITCODE = 0; 'Docker Compose version v5.5.1' }
function global:podman {
    $a = $args -join ' '
    $global:LASTEXITCODE = 0
    # What a new PC does, found on the Windows VM: `podman compose` connects
    # to Podman's machine first, and before Setup has created one it fails.
    if ($a -eq 'compose version' -and -not $global:MachineStarted) {
        'Cannot connect to Podman. Please verify your connection to the Linux system'
        $global:LASTEXITCODE = 125
    }
    elseif ($a -eq 'compose version') { 'Docker Compose version v5.5.1' }
    elseif ($a -like 'machine init*') { $global:MachineStarted = $true }
    elseif ($a -like 'machine start*') { $global:MachineStarted = $true; $global:MachineStarts++ }
    elseif ($a -eq '--version') { 'podman version 5.8.3' }
    elseif ($a -like 'machine list*Name*') { 'podman-machine-default' }
    elseif ($a -like 'machine list*Running*') { "$global:MachineRunning".ToLower() }
}
function global:wsl.exe {
    $global:WslCalls += , ($args -join ' ')
    $global:LASTEXITCODE = 0
    # The in-box stub, as the Windows VM showed: no --install without a
    # console, and --version answers only once WSL itself is installed.
    if ($args[0] -eq '--install') { 'The Windows Subsystem for Linux is not installed.'; $global:LASTEXITCODE = 1 }
    if ($args[0] -eq '--version' -and -not $global:WslInstalled) { $global:LASTEXITCODE = 1 }
    if ($args[0] -eq '--status') { $global:LASTEXITCODE = -1 }
}
# The Windows build, and the rest of what the report reads about the PC. The
# Windows runner is Server 2022, build 20348, which Setup would rightly
# refuse, so the build is always the scenario's.
function global:Get-CimInstance {
    param($ClassName, $ErrorAction)
    [pscustomobject]@{
        BuildNumber = "$global:WinBuild"; Caption = 'Microsoft Windows 11 Pro'; Version = "10.0.$global:WinBuild"
        OSArchitecture = '64-bit'; TotalVisibleMemorySize = 16777216; Name = 'Test CPU'; VirtualizationFirmwareEnabled = $true
    }
}
function global:Enable-WindowsOptionalFeature {
    if ($global:VmState -eq 'THROW') { throw 'unreadable' }
    $global:VmState = $global:AfterInstall
    [pscustomobject]@{ RestartNeeded = $true }
}
function global:Get-WindowsOptionalFeature {
    if ($global:VmState -eq 'THROW') { throw 'unreadable' }
    [pscustomobject]@{ State = $global:VmState }
}
function global:powershell.exe { $global:Installed = $true; $global:LASTEXITCODE = $global:InstallCode }
function global:Set-ItemProperty { param($Path, $Name, $Value) $global:RunOnce = $Value }
function global:python {
    # A Python only once one is "installed"; before that, a broken one, like
    # the Store's placeholder on a new PC.
    $global:LASTEXITCODE = $(if ($global:PythonInstalled) { 0 } else { 1 })
}
# "This PC has no Python but the fake one": the Windows runner has a real
# Python on PATH, which Setup would rightly find and use, so the lookup is
# faked for python and py and passed through for everything else.
function global:Get-Command {
    if ($args.Count -gt 0 -and ($args[0] -eq 'python' -or $args[0] -eq 'py')) {
        if ($args[0] -eq 'python') { return (Microsoft.PowerShell.Core\Get-Command -Name python -CommandType Function) }
        return
    }
    Microsoft.PowerShell.Core\Get-Command @args
}
function global:Start-Process {
    param($FilePath, $ArgumentList, [switch]$Wait, [switch]$PassThru, $Verb, $WindowStyle, $ErrorAction)
    if ("$FilePath" -match 'python-.*\.exe$') {
        $global:PythonRuns++
        $global:PythonInstalled = $global:PythonInstallerWorks
        return [pscustomobject]@{ ExitCode = $(if ($global:PythonInstallerWorks) { 0 } else { 1603 }) }
    }
    if ("$FilePath" -match 'vc_redist\.x64\.exe$') {
        $global:VcRuns++
        $global:VcArguments = "$ArgumentList"
        if ($global:VcInstallWorks) { New-FakeVcRuntime }
        return [pscustomobject]@{ ExitCode = $global:VcExitCode }
    }
    if ("$FilePath" -match 'msiexec') {
        $global:MsiRuns++
        $global:WslInstalled = $global:MsiInstallsWsl
        return [pscustomobject]@{ ExitCode = $(if ($global:MsiInstallsWsl) { 3010 } else { 1603 }) }
    }
}
function global:New-FakeVcRuntime {
    foreach ($dll in 'vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll') {
        Set-Content -Path (Join-Path $FakeSystem32 $dll) -Value 'dll'
    }
}
function global:Start-Sleep { }
function global:Read-Host { }

$script:Pass = 0
$script:Fail = 0

function Invoke-Scenario {
    param([string]$Name, [string]$Initial, [string]$AfterInstall, [int]$Want, [scriptblock]$Check, [int]$InstallCode = 0,
          [bool]$WslInstalled = $true, [bool]$MsiInstallsWsl = $true, [bool]$DownloadMatches = $true,
          [bool]$PythonInstalled = $true, [bool]$PythonInstallerWorks = $true,
          [int]$WinBuild = 26200, [string]$WslConfig = $null, [bool]$MachineRunning = $true,
          [bool]$VcPresent = $true, [bool]$VcInstallWorks = $true, [int]$VcExitCode = 0,
          [string]$VcSignatureStatus = 'Valid',
          [string]$VcSignedBy = 'CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US')
    $global:VmState = $Initial
    $global:AfterInstall = $AfterInstall
    $global:InstallCode = $InstallCode
    $global:WslCalls = @()
    $global:RunOnce = $null
    $global:Installed = $false
    $global:MachineStarted = $false
    $global:WslInstalled = $WslInstalled
    $global:MsiInstallsWsl = $MsiInstallsWsl
    $global:DownloadMatches = $DownloadMatches
    $global:Downloads = @()
    $global:MsiRuns = 0
    $global:PythonInstalled = $PythonInstalled
    $global:PythonInstallerWorks = $PythonInstallerWorks
    $global:PythonRuns = 0
    $global:WinBuild = $WinBuild
    $global:MachineRunning = $MachineRunning
    $global:MachineStarts = 0
    $global:VcInstallWorks = $VcInstallWorks
    $global:VcExitCode = $VcExitCode
    $global:VcSignatureStatus = $VcSignatureStatus
    $global:VcSignedBy = $VcSignedBy
    $global:VcRuns = 0
    $global:VcArguments = $null
    Get-ChildItem -Path $FakeSystem32 | Remove-Item -Force
    if ($VcPresent) { New-FakeVcRuntime }
    Remove-Item -Force -Path $WslConfigPath -ErrorAction SilentlyContinue
    if ($WslConfig) { [System.IO.File]::WriteAllText($WslConfigPath, $WslConfig) }
    Remove-Item -Recurse -Force -Path $Stage -ErrorAction SilentlyContinue
    Get-ChildItem -Path $env:TEMP, $Desktop -Filter 'Askwell*' -ErrorAction SilentlyContinue | Remove-Item -Force
    $ErrorActionPreference = 'Continue'
    $env:SystemRoot = $FakeSystemRoot
    try {
        $global:Output = (& $Boot -Root $Tree *>&1 | Out-String)
        $code = $LASTEXITCODE
    } finally {
        $env:SystemRoot = $RealSystemRoot
    }
    $ErrorActionPreference = 'Stop'
    $ok = ($code -eq $Want) -and [bool](& $Check)
    if ($ok) { $script:Pass++; Write-Host "  ok    $Name" }
    else {
        $script:Fail++
        Write-Host "  FAIL  $Name (exit $code, want $Want)"
        Get-Content (Join-Path $env:TEMP 'AskwellSetup.log') -ErrorAction SilentlyContinue |
            Select-Object -Last 12 | ForEach-Object { Write-Host "        | $_" }
    }
}

function Get-Report {
    Get-ChildItem -Path $Desktop -Filter 'Askwell-Setup-report-*.txt' -ErrorAction SilentlyContinue | Select-Object -First 1
}

Write-Host 'windows setup'

Invoke-Scenario 'fresh PC: enables WSL, keeps its files, registers one resume, asks one restart' 'Disabled' 'EnablePending' 30 {
    ($global:RunOnce -match ' -Resume$') -and
    (Test-Path (Join-Path $Stage 'deploy\windows\setup\setup-bootstrap.ps1')) -and
    -not $global:Installed -and -not (Get-Report) -and -not ($global:WslCalls -match '^--install')
} -WslInstalled $false
Invoke-Scenario 'platform on but WSL itself missing: installs it, then one restart' 'Enabled' 'Enabled' 30 {
    $global:WslInstalled -and ($global:RunOnce -match ' -Resume$')
} -WslInstalled $false
Invoke-Scenario 'WSL installer fails: an error, never a restart' 'Enabled' 'Enabled' 32 {
    -not $global:RunOnce -and [bool](Get-Report) -and $global:MsiRuns -eq 1
} -WslInstalled $false -MsiInstallsWsl $false
Invoke-Scenario 'a download that fails its checksum is never run' 'Enabled' 'Enabled' 32 {
    $global:MsiRuns -eq 0 -and $global:Downloads.Count -eq 1 -and -not $global:RunOnce
} -WslInstalled $false -DownloadMatches $false
Invoke-Scenario 'the WSL installer comes from Microsoft, pinned' 'Enabled' 'Enabled' 30 {
    $global:Downloads -contains 'https://github.com/microsoft/WSL/releases/download/2.7.13/wsl.2.7.13.0.x64.msi'
} -WslInstalled $false
Invoke-Scenario 'after the restart: WSL enabled, no distribution, installs with no second restart' 'Enabled' 'Enabled' 0 {
    $global:Installed -and -not $global:RunOnce -and -not ($global:WslCalls -contains '--status')
}
Invoke-Scenario 'WSL already enabled: straight through' 'Enabled' 'Enabled' 0 { $global:Installed -and -not $global:RunOnce }
# The Windows VM, 0.9.6: after `wsl --install` Windows reported the feature
# as Enabled, not EnablePending, while saying the change needs a reboot. Setup
# went on and `podman machine init` failed with HCS_E_SERVICE_NOT_AVAILABLE.
Invoke-Scenario 'enabled by this run but reported Enabled: still asks one restart' 'Disabled' 'Enabled' 30 {
    ($global:RunOnce -match ' -Resume$') -and -not $global:Installed
} -WslInstalled $false
# The Windows VM, 0.9.6: a new PC has no Python, only the Store placeholder.
Invoke-Scenario 'no Python: installs python.org 3.13, pinned, then carries on' 'Enabled' 'Enabled' 0 {
    $global:PythonRuns -eq 1 -and $global:Installed -and
    ($global:Downloads -contains 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.exe')
} -PythonInstalled $false
Invoke-Scenario 'Python does not install: code 25, with a report' 'Enabled' 'Enabled' 25 {
    [bool](Get-Report) -and -not $global:Installed
} -PythonInstalled $false -PythonInstallerWorks $false
Invoke-Scenario 'restart already pending: asks once' 'EnablePending' 'EnablePending' 30 { $global:RunOnce -match ' -Resume$' }
Invoke-Scenario 'WSL cannot be enabled: an error, never a restart' 'Disabled' 'Disabled' 32 { -not $global:RunOnce -and -not $global:Installed }
Invoke-Scenario 'feature state unreadable: an error, never a restart' 'THROW' 'THROW' 32 { -not $global:RunOnce }
Invoke-Scenario 'a failure saves a report with the log, names replaced' 'Disabled' 'Disabled' 32 {
    $report = Get-Report
    if (-not $report) { return $false }
    $text = [System.IO.File]::ReadAllText($report.FullName)
    ($text -match 'send this file') -and ($text -match 'Result: code 32') -and
    ($text -match '<profile>') -and ($text -notmatch 'nimal') -and ($text -notmatch [regex]::Escape($Scratch))
} -WslInstalled $false -MsiInstallsWsl $false
Invoke-Scenario "install.ps1 failing also saves a report" 'Enabled' 'Enabled' 9 { [bool](Get-Report) } -InstallCode 9
Invoke-Scenario 'success leaves no report and no log' 'Enabled' 'Enabled' 0 {
    -not (Get-Report) -and -not (Test-Path (Join-Path $env:TEMP 'AskwellSetup.log'))
}

# M11-FIX-DEPLOY-223: the containers reach llama.cpp on this PC's 127.0.0.1
# only under WSL's mirrored networking, which needs Windows 11 22H2.
Invoke-Scenario 'mirrored set, machine restarted: WSL shut down, machine started again' 'Enabled' 'Enabled' 0 {
    $text = [System.IO.File]::ReadAllText($WslConfigPath)
    ($text -match 'networkingMode=mirrored') -and ($global:WslCalls -contains '--shutdown') -and
    $global:MachineStarts -eq 1 -and $global:Installed -and ($global:Output -match 'Created .*\.wslconfig')
}
Invoke-Scenario 'networkingMode=nat is changed, the log says so, other settings kept' 'Enabled' 'Enabled' 0 {
    $text = [System.IO.File]::ReadAllText($WslConfigPath)
    ($text -match 'networkingMode=mirrored') -and ($text -match 'memory=8GB') -and ($text -notmatch 'nat') -and
    ($global:Output -match 'Changed networkingMode from nat to mirrored') -and ($global:WslCalls -contains '--shutdown')
} -WslConfig "[wsl2]`r`nmemory=8GB`r`nnetworkingMode=nat`r`n"
Invoke-Scenario 'already mirrored: nothing written, no WSL restart' 'Enabled' 'Enabled' 0 {
    -not ($global:WslCalls -contains '--shutdown') -and $global:MachineStarts -eq 0 -and $global:Installed -and
    ($global:Output -match 'already uses mirrored networking')
} -WslConfig "[wsl2]`r`nnetworkingMode=mirrored`r`n"
Invoke-Scenario 'mirrored set before a stopped machine starts: started once, no WSL restart' 'Enabled' 'Enabled' 0 {
    -not ($global:WslCalls -contains '--shutdown') -and $global:MachineStarts -eq 1 -and
    ([System.IO.File]::ReadAllText($WslConfigPath) -match 'networkingMode=mirrored')
} -MachineRunning $false
Invoke-Scenario 'Windows too old: refused before anything is installed' 'Disabled' 'EnablePending' 26 {
    $report = Get-Report
    [bool]$report -and ([System.IO.File]::ReadAllText($report.FullName) -match 'Result: code 26') -and
    ($global:Output -match 'build 22621') -and -not $global:Installed -and -not $global:RunOnce -and
    $global:Downloads.Count -eq 0 -and $global:PythonRuns -eq 0 -and -not (Test-Path $WslConfigPath)
} -WinBuild 19045 -WslInstalled $false -PythonInstalled $false
Invoke-Scenario 'Windows 11 21H2 is refused too: no mirrored networking' 'Enabled' 'Enabled' 26 { -not $global:Installed } -WinBuild 22000
Invoke-Scenario 'Windows 11 22H2, the minimum, installs' 'Enabled' 'Enabled' 0 { $global:Installed } -WinBuild 22621

# M11-FIX-DEPLOY-225: every llama-server.exe needs Microsoft's Visual C++
# runtime, and a new Windows has none.
$VcUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
Invoke-Scenario 'no Visual C++ runtime: Microsoft''s, signature checked, installed quietly, then Askwell' 'Enabled' 'Enabled' 0 {
    $global:VcRuns -eq 1 -and $global:Installed -and ($global:Downloads -contains $VcUrl) -and
    ($global:VcArguments -eq '/install /quiet /norestart') -and
    ($global:Output -match 'signature Valid, signed by: CN=Microsoft Corporation,') -and
    ($global:Output -match 'Installer version')
} -VcPresent $false
Invoke-Scenario 'a runtime installer not signed by Microsoft is refused and never run' 'Enabled' 'Enabled' 28 {
    $report = Get-Report
    $global:VcRuns -eq 0 -and -not $global:Installed -and [bool]$report -and
    ([System.IO.File]::ReadAllText($report.FullName) -match 'Result: code 28') -and
    ($global:Output -match 'not validly signed by Microsoft') -and
    -not (Test-Path (Join-Path $env:TEMP 'vc_redist.x64.exe'))
} -VcPresent $false -VcSignedBy 'CN=Contoso Ltd, O=Contoso Ltd, C=US'
Invoke-Scenario 'a runtime installer whose signature is broken is refused and never run' 'Enabled' 'Enabled' 28 {
    $global:VcRuns -eq 0 -and -not $global:Installed
} -VcPresent $false -VcSignatureStatus 'HashMismatch'
Invoke-Scenario 'runtime present: the step is skipped, nothing downloaded' 'Enabled' 'Enabled' 0 {
    $global:VcRuns -eq 0 -and $global:Installed -and -not ($global:Downloads -contains $VcUrl) -and
    ($global:Output -match 'Visual C\+\+ runtime: ')
}
Invoke-Scenario 'a newer runtime already installed (1638) counts as success' 'Enabled' 'Enabled' 0 {
    $global:VcRuns -eq 1 -and $global:Installed -and ($global:Output -match 'newer version is already installed')
} -VcPresent $false -VcExitCode 1638
Invoke-Scenario 'the runtime installer fails: code 28, with a report' 'Enabled' 'Enabled' 28 {
    $global:VcRuns -eq 1 -and -not $global:Installed -and [bool](Get-Report) -and ($global:Output -match 'stopped with code 1603')
} -VcPresent $false -VcInstallWorks $false -VcExitCode 1603

Remove-Item -Recurse -Force -Path $Scratch -ErrorAction SilentlyContinue
Write-Host ''
Write-Host "$script:Pass passed, $script:Fail failed"
if ($script:Fail -gt 0) { exit 1 }
exit 0
