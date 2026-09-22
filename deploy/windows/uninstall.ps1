<#
.SYNOPSIS
    Uninstalls Askwell (M7-PACK-DEPLOY-140). Mirrors deploy/linux/uninstall.sh:
    removes application files, the Start-menu entry and the Startup-folder
    session-start shortcut. Leaves the data directory — and therefore every
    document Askwell indexed, in place on the user's own disk untouched by
    Askwell — alone unless -PurgeData is given, which still asks for
    confirmation before deleting anything.
#>

[CmdletBinding()]
param(
    [string]$DataDir,
    [switch]$PurgeData,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Here 'lib.ps1')

if (-not $DataDir) { $DataDir = Get-AskwellDataDir }
$InstallPrefix = Get-AskwellInstallPrefix
$StartMenuDir = Get-AskwellStartMenuDir
$StartupDir = Get-AskwellStartupDir

function Confirm-Askwell {
    param([string]$Prompt)
    if ($Yes) { return $true }
    $reply = Read-Host "$Prompt [y/N]"
    return $reply -match '^[yY]'
}

function Main {
    Remove-Item -Path (Join-Path $StartMenuDir 'Askwell.lnk') -Force -ErrorAction SilentlyContinue
    Remove-Item -Path (Join-Path $StartupDir 'Askwell.lnk') -Force -ErrorAction SilentlyContinue
    Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Askwell' -Recurse -Force -ErrorAction SilentlyContinue

    if (Test-Path $InstallPrefix) {
        $composeFile = Join-Path $InstallPrefix 'compose.yaml'
        if ((Get-Command podman -ErrorAction SilentlyContinue) -and (Test-Path $composeFile)) {
            Push-Location $InstallPrefix
            try { podman compose down 2>$null | Out-Null } catch { }
            Pop-Location
        }
        Remove-Item -Path $InstallPrefix -Recurse -Force
    }
    Write-AskwellSay 'Askwell application files removed.'

    if ($PurgeData) {
        if (Test-Path $DataDir) {
            if (-not (Confirm-Askwell "Delete Askwell's data directory ($DataDir)? This removes your corpus's index, memory and settings — not the files themselves, which live where you put them.")) {
                Write-AskwellSay "Data directory left in place: $DataDir"
                return
            }
            Remove-Item -Path $DataDir -Recurse -Force
            Write-AskwellSay "Data directory removed: $DataDir"
        }
    } elseif (Test-Path $DataDir) {
        Write-AskwellSay "Data directory left in place: $DataDir (use -PurgeData to remove it)"
    }
}

Main
