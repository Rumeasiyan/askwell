<#
.SYNOPSIS
    Uninstalls Askwell (M7-PACK-DEPLOY-140). Mirrors deploy/linux/uninstall.sh:
    removes application files, the Start-menu entry and the Startup-folder
    session-start shortcut. Leaves the data directory — and therefore every
    document Askwell indexed, in place on the user's own disk untouched by
    Askwell — alone unless -PurgeData is given, which still asks for
    confirmation before deleting anything.

    -PurgeData removes both places Askwell keeps data (issue #700): the data
    directory and the Podman volumes that hold the database. See
    deploy/linux/uninstall.sh for why removing only the directory was wrong.
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
    # M7-PACK-DEPLOY-142: unregister the stack and inference scheduled tasks
    # before the `podman compose down` fallback below — that fallback exists
    # for the case where the tasks were never registered at all (e.g.
    # Podman/Python were missing at install time), not as the primary stop
    # path.
    Unregister-ScheduledTask -TaskName (Get-AskwellInferenceTaskName) -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName (Get-AskwellStackTaskName) -Confirm:$false -ErrorAction SilentlyContinue
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
        $volumes = $script:AskwellVolumes -join ' '
        if (-not (Confirm-Askwell "Delete all of Askwell's data? This removes its database (your corpus's index and extracted text, memory, conversations and audit log), imported databases, stored backups and crash reports, and the data directory ($DataDir`: settings, models, logs). Your own files are not touched; they stay where you put them. Copy out any backup you want to keep first - there is no undo.")) {
            Write-AskwellSay "Askwell's data left in place: the data directory $DataDir and the database volumes ($volumes)."
            return
        }
        Remove-AskwellData
    } else {
        if (Test-Path $DataDir) {
            Write-AskwellSay "Data directory left in place: $DataDir (use -PurgeData to remove it)"
        }
        Write-AskwellSay "Askwell's database volumes are also left in place, so reinstalling keeps your index and memory (use -PurgeData to remove them)."
    }
}

# Says only what it did: each half is reported from what is on disk
# afterwards, and a volume that would not go is named with the command that
# removes it.
function Remove-AskwellData {
    $failed = $false
    $volumes = $script:AskwellVolumes -join ' '
    $podman = Get-Command podman -ErrorAction SilentlyContinue
    if ($podman) {
        $left = Remove-AskwellVolumes -Podman $podman.Source
        if ($left.Count -eq 0) {
            Write-AskwellSay "Database volumes removed: $volumes"
        } else {
            Write-AskwellSay "Could not remove these volumes: $($left -join ' '). Stop anything still using them, then run: podman volume rm -f $($left -join ' ')"
            $failed = $true
        }
    } else {
        Write-AskwellSay "Podman is not on PATH, so the database volumes ($volumes) could not be checked or removed. If they exist, remove them with: podman volume rm -f $volumes"
        $failed = $true
    }
    if (Test-Path $DataDir) {
        Remove-Item -Path $DataDir -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $DataDir) {
            Write-AskwellSay "Could not remove the data directory: $DataDir"
            $failed = $true
        } else {
            Write-AskwellSay "Data directory removed: $DataDir"
        }
    }
    if ($failed) {
        Write-AskwellDie "Askwell's data was not fully removed (see above)."
        exit 1
    }
    Write-AskwellSay "All of Askwell's data has been removed."
}

Main
