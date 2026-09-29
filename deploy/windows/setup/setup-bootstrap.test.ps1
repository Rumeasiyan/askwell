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
$env:COMPUTERNAME = 'NIMAL-LAPTOP'
New-Item -ItemType Directory -Force -Path $env:TEMP, $env:ProgramData | Out-Null
$Stage = Join-Path $env:ProgramData 'AskwellSetup'
$Desktop = [Environment]::GetFolderPath('Desktop')
if (-not $Desktop -or -not (Test-Path $Desktop)) { $Desktop = $env:TEMP }

function global:winget { $global:LASTEXITCODE = 0 }
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
    elseif ($a -like 'machine start*' -or $a -like 'machine init*') { $global:MachineStarted = $true }
    elseif ($a -eq '--version') { 'podman version 5.8.3' }
    elseif ($a -like 'machine list*Name*') { 'podman-machine-default' }
    elseif ($a -like 'machine list*Running*') { 'true' }
}
function global:wsl.exe {
    $global:WslCalls += , ($args -join ' ')
    $global:LASTEXITCODE = 0
    if ($args[0] -eq '--install') { $global:VmState = $global:AfterInstall; 'Installing for NIMAL-LAPTOP\nimal.perera' }
    if ($args[0] -eq '--status') { $global:LASTEXITCODE = -1 }
}
function global:Get-WindowsOptionalFeature {
    if ($global:VmState -eq 'THROW') { throw 'unreadable' }
    [pscustomobject]@{ State = $global:VmState }
}
function global:powershell.exe { $global:Installed = $true; $global:LASTEXITCODE = $global:InstallCode }
function global:Set-ItemProperty { param($Path, $Name, $Value) $global:RunOnce = $Value }
function global:Start-Process { }
function global:Start-Sleep { }
function global:Read-Host { }

$script:Pass = 0
$script:Fail = 0

function Invoke-Scenario {
    param([string]$Name, [string]$Initial, [string]$AfterInstall, [int]$Want, [scriptblock]$Check, [int]$InstallCode = 0)
    $global:VmState = $Initial
    $global:AfterInstall = $AfterInstall
    $global:InstallCode = $InstallCode
    $global:WslCalls = @()
    $global:RunOnce = $null
    $global:Installed = $false
    $global:MachineStarted = $false
    Remove-Item -Recurse -Force -Path $Stage -ErrorAction SilentlyContinue
    Get-ChildItem -Path $env:TEMP, $Desktop -Filter 'Askwell*' -ErrorAction SilentlyContinue | Remove-Item -Force
    $ErrorActionPreference = 'Continue'
    & $Boot -Root $Tree *> $null
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $ok = ($code -eq $Want) -and [bool](& $Check)
    if ($ok) { $script:Pass++; Write-Host "  ok    $Name" }
    else { $script:Fail++; Write-Host "  FAIL  $Name (exit $code, want $Want)" }
}

function Get-Report {
    Get-ChildItem -Path $Desktop -Filter 'Askwell-Setup-report-*.txt' -ErrorAction SilentlyContinue | Select-Object -First 1
}

Write-Host 'windows setup'

Invoke-Scenario 'fresh PC: enables WSL, keeps its files, registers one resume, asks one restart' 'Disabled' 'EnablePending' 30 {
    ($global:RunOnce -match ' -Resume$') -and
    (Test-Path (Join-Path $Stage 'deploy\windows\setup\setup-bootstrap.ps1')) -and
    -not $global:Installed -and -not (Get-Report)
}
Invoke-Scenario 'after the restart: WSL enabled, no distribution, installs with no second restart' 'Enabled' 'Enabled' 0 {
    $global:Installed -and -not $global:RunOnce -and -not ($global:WslCalls -contains '--status')
}
Invoke-Scenario 'WSL already enabled: straight through' 'Enabled' 'Enabled' 0 { $global:Installed -and -not $global:RunOnce }
# The Windows VM, 0.9.6: after `wsl --install` Windows reported the feature
# as Enabled, not EnablePending, while saying the change needs a reboot. Setup
# went on and `podman machine init` failed with HCS_E_SERVICE_NOT_AVAILABLE.
Invoke-Scenario 'enabled by this run but reported Enabled: still asks one restart' 'Disabled' 'Enabled' 30 {
    ($global:RunOnce -match ' -Resume$') -and -not $global:Installed
}
Invoke-Scenario 'restart already pending: asks once' 'EnablePending' 'EnablePending' 30 { $global:RunOnce -match ' -Resume$' }
Invoke-Scenario 'WSL cannot be enabled: an error, never a restart' 'Disabled' 'Disabled' 32 { -not $global:RunOnce -and -not $global:Installed }
Invoke-Scenario 'feature state unreadable: an error, never a restart' 'THROW' 'THROW' 32 { -not $global:RunOnce }
Invoke-Scenario 'a failure saves a report with the log, names replaced' 'Disabled' 'Disabled' 32 {
    $report = Get-Report
    if (-not $report) { return $false }
    $text = [System.IO.File]::ReadAllText($report.FullName)
    ($text -match 'send this file') -and ($text -match 'Result: code 32') -and
    ($text -match 'Installing for <pc>.<user>') -and ($text -notmatch 'nimal')
}
Invoke-Scenario "install.ps1 failing also saves a report" 'Enabled' 'Enabled' 9 { [bool](Get-Report) } -InstallCode 9
Invoke-Scenario 'success leaves no report and no log' 'Enabled' 'Enabled' 0 {
    -not (Get-Report) -and -not (Test-Path (Join-Path $env:TEMP 'AskwellSetup.log'))
}

Remove-Item -Recurse -Force -Path $Scratch -ErrorAction SilentlyContinue
Write-Host ''
Write-Host "$script:Pass passed, $script:Fail failed"
if ($script:Fail -gt 0) { exit 1 }
exit 0
