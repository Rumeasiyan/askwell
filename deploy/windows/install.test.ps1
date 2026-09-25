# Tests for the Windows installer's logic (M7-PACK-DEPLOY-140). See
# deploy/linux/install.test.sh for the pattern this follows.
#
# Tests lib.ps1's pure functions only — never a real winget, a real Podman
# install, or real WSL2. A machine that could exercise the whole installer
# (a clean Windows VM with virtualisation initially off) is exactly the
# manual walkthrough this ticket's docs/manual-tests file requires, and is
# not this suite's job to fake convincingly.
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $Here 'lib.ps1')

$script:Pass = 0
$script:Fail = 0

function Test-Ok { param([string]$Name) $script:Pass++; Write-Host "  ok    $Name" }
function Test-Bad { param([string]$Name, $Got, $Want) $script:Fail++; Write-Host "  FAIL  $Name (want '$Want', got '$Got')" }
function Test-Check {
    param([string]$Name, $Got, $Want)
    if ("$Got" -eq "$Want") { Test-Ok $Name } else { Test-Bad $Name $Got $Want }
}

function New-AskwellTempDir {
    $dir = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid())
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    return $dir
}

Write-Host 'windows installer'

# --- virtualisation detection -------------------------------------------------
$firmwareOn = @"
Hyper-V Requirements:      VM Monitor Mode Extensions: Yes
                            Virtualization Enabled In Firmware: Yes
                            Second Level Address Translation: Yes
                            Data Execution Prevention Available: Yes
"@
(Test-AskwellVirtualizationEnabled $firmwareOn) | Out-Null
if (Test-AskwellVirtualizationEnabled $firmwareOn) { Test-Ok 'firmware flag Yes reads as enabled' } else { Test-Bad 'firmware flag Yes reads as enabled' $false $true }

$firmwareOff = @"
Hyper-V Requirements:      VM Monitor Mode Extensions: Yes
                            Virtualization Enabled In Firmware: No
"@
if (-not (Test-AskwellVirtualizationEnabled $firmwareOff)) { Test-Ok 'firmware flag No reads as disabled' } else { Test-Bad 'firmware flag No reads as disabled' $true $false }

$hypervisorRunning = @"
Hyper-V Requirements:      A hypervisor has been detected. Features required for Hyper-V will not be displayed.
"@
if (Test-AskwellVirtualizationEnabled $hypervisorRunning) { Test-Ok 'an already-running hypervisor reads as enabled' } else { Test-Bad 'an already-running hypervisor reads as enabled' $false $true }

# --- Windows build ------------------------------------------------------------
if (Test-AskwellWindowsBuildSupported 22631) { Test-Ok 'Windows 11 build meets the WSL2 minimum' } else { Test-Bad 'Windows 11 build meets the WSL2 minimum' $false $true }
if (-not (Test-AskwellWindowsBuildSupported 18363)) { Test-Ok 'a pre-WSL2 build is refused' } else { Test-Bad 'a pre-WSL2 build is refused' $true $false }

# --- version comparison --------------------------------------------------------
Test-Check 'equal versions compare 0' (Compare-AskwellVersion '4.3.0' '4.3.0') 0
Test-Check 'shorter version pads with zero (4.3 == 4.3.0)' (Compare-AskwellVersion '4.3' '4.3.0') 0
Test-Check '4.9.4 > 4.3' (Compare-AskwellVersion '4.9.4' '4.3') 1
Test-Check '3.4 < 4.3' (Compare-AskwellVersion '3.4' '4.3') -1
if (Test-AskwellVersionAtLeast '4.9.4' '4.3') { Test-Ok 'Test-AskwellVersionAtLeast true case' } else { Test-Bad 'Test-AskwellVersionAtLeast true case' $false $true }
if (-not (Test-AskwellVersionAtLeast '3.4' '4.3')) { Test-Ok 'Test-AskwellVersionAtLeast false case' } else { Test-Bad 'Test-AskwellVersionAtLeast false case' $true $false }

# --- podman version parsing -----------------------------------------------------
Test-Check "parses podman's own version banner" (ConvertFrom-AskwellPodmanVersion 'podman version 4.9.4') '4.9.4'
if (Test-AskwellPodmanMeetsMinimum 'podman version 5.8.4') { Test-Ok '5.8.4 meets the default minimum' } else { Test-Bad '5.8.4 meets the default minimum' $false $true }
if (-not (Test-AskwellPodmanMeetsMinimum 'podman version 3.4.0')) { Test-Ok '3.4.0 does not meet the default minimum' } else { Test-Bad '3.4.0 does not meet the default minimum' $true $false }
if (-not (Test-AskwellPodmanMeetsMinimum 'not even a version string')) { Test-Ok 'unparseable version string is a refusal, not a guess' } else { Test-Bad 'unparseable version string is a refusal, not a guess' $true $false }

# --- disk space ------------------------------------------------------------------
Test-Check 'Format-AskwellBytes renders GB' (Format-AskwellBytes 8000000000) '7.5 GB'
Test-Check 'Format-AskwellBytes renders MB' (Format-AskwellBytes 5000000) '4.8 MB'

# --- path length (edge case: MAX_PATH) --------------------------------------------
if (Test-AskwellPathWithinLimit 'C:\Users\anna\AppData\Local\Askwell\app\askwell-shell.exe') { Test-Ok 'a normal install path is within the limit' } else { Test-Bad 'a normal install path is within the limit' $false $true }
$longPath = 'C:\' + ('a' * 260) + '\askwell-shell.exe'
if (-not (Test-AskwellPathWithinLimit $longPath)) { Test-Ok 'a path past MAX_PATH is refused' } else { Test-Bad 'a path past MAX_PATH is refused' $true $false }

# --- paths -------------------------------------------------------------------------
$env:ASKWELL_DATA_DIR = $null
$env:LOCALAPPDATA = 'C:\Users\anna\AppData\Local'
Remove-Item Env:\ASKWELL_DATA_DIR -ErrorAction SilentlyContinue
Test-Check 'data dir defaults under LOCALAPPDATA' (Get-AskwellDataDir) 'C:\Users\anna\AppData\Local\Askwell'
$env:ASKWELL_DATA_DIR = 'D:\custom\data'
Test-Check 'data dir honours override' (Get-AskwellDataDir) 'D:\custom\data'
Remove-Item Env:\ASKWELL_DATA_DIR -ErrorAction SilentlyContinue

# --- previous install state -----------------------------------------------------
$tmp = New-AskwellTempDir
if (-not (Test-AskwellPreviousInstall (Join-Path $tmp 'nowhere'))) { Test-Ok 'no install record means no previous install' } else { Test-Bad 'no install record means no previous install' $true $false }

$dataDir = Join-Path $tmp 'data'
Write-AskwellInstallRecord -DataDir $dataDir -Version '0.7.8' -Method 'install'
if (Test-AskwellPreviousInstall $dataDir) { Test-Ok 'a written record is detected as a previous install' } else { Test-Bad 'a written record is detected as a previous install' $false $true }
Test-Check 'the recorded version reads back' (Get-AskwellPreviousInstallVersion $dataDir) '0.7.8'

# --- secrets: mirrors the #584 fix -----------------------------------------------
$hex1 = New-AskwellRandomHex 32
$hex2 = New-AskwellRandomHex 32
if ($hex1 -match '^[0-9a-f]+$') { Test-Ok 'New-AskwellRandomHex produces lowercase hex' } else { Test-Bad 'New-AskwellRandomHex produces lowercase hex' $hex1 '[0-9a-f]+' }
Test-Check 'New-AskwellRandomHex(32) is 64 hex characters' $hex1.Length 64
if ($hex1 -ne $hex2) { Test-Ok 'two calls to New-AskwellRandomHex do not repeat' } else { Test-Bad 'two calls to New-AskwellRandomHex do not repeat' $hex1 $hex2 }

$envFile = Join-Path $tmp 'env-under-test'
@'
POSTGRES_PASSWORD=change-me
POSTGRES_APP_PASSWORD=change-me-too
POSTGRES_READONLY_PASSWORD=change-me-as-well
SANDBOX_POSTGRES_PASSWORD=change-me-in-the-sandbox-too
SANDBOX_OWNER_PASSWORD=change-me-sandbox-owner
SANDBOX_READONLY_PASSWORD=change-me-sandbox-readonly
ASKWELL_SANDBOX_OWNER_PASSWORD=change-me-sandbox-owner
ASKWELL_SANDBOX_READONLY_PASSWORD=change-me-sandbox-readonly
'@ | Set-Content -Path $envFile -Encoding utf8

Set-AskwellEnvPasswords $envFile
$envContent = Get-Content $envFile -Raw
if ($envContent -notmatch 'change-me') { Test-Ok 'no change-me placeholder survives generation' } else { Test-Bad 'no change-me placeholder survives generation' 'still present' 'gone' }

$lines = Get-Content $envFile
$sandboxOwner = ($lines | Where-Object { $_ -match '^SANDBOX_OWNER_PASSWORD=' }) -replace '^SANDBOX_OWNER_PASSWORD=', ''
$askwellOwner = ($lines | Where-Object { $_ -match '^ASKWELL_SANDBOX_OWNER_PASSWORD=' }) -replace '^ASKWELL_SANDBOX_OWNER_PASSWORD=', ''
$sandboxReadonly = ($lines | Where-Object { $_ -match '^SANDBOX_READONLY_PASSWORD=' }) -replace '^SANDBOX_READONLY_PASSWORD=', ''
$askwellReadonly = ($lines | Where-Object { $_ -match '^ASKWELL_SANDBOX_READONLY_PASSWORD=' }) -replace '^ASKWELL_SANDBOX_READONLY_PASSWORD=', ''
Test-Check 'SANDBOX_OWNER_PASSWORD and ASKWELL_SANDBOX_OWNER_PASSWORD stay the same credential' $sandboxOwner $askwellOwner
Test-Check 'SANDBOX_READONLY_PASSWORD and ASKWELL_SANDBOX_READONLY_PASSWORD stay the same credential' $sandboxReadonly $askwellReadonly

$allPasswords = $lines | Where-Object { $_ -match '=' } | ForEach-Object { ($_ -split '=', 2)[1] }
$distinctCount = ($allPasswords | Select-Object -Unique).Count
Test-Check 'the six stored passwords are all distinct from each other' $distinctCount 6

# --- M8-FIX-SEC-177: Redis passwords, fresh and on upgrade -----------------------
$redisDir = New-AskwellTempDir
$redisEnv = Join-Path $redisDir '.env'
@'
REDIS_API_PASSWORD=change-me-redis-api
REDIS_WORKER_PASSWORD=change-me-redis-worker
REDIS_PROXY_PASSWORD=change-me-redis-proxy
'@ | Set-Content -Path $redisEnv -Encoding utf8
Set-AskwellRedisPasswords $redisEnv
$redisContent = Get-Content $redisEnv -Raw
if ($redisContent -notmatch 'change-me') { Test-Ok 'a fresh .env keeps no Redis placeholder' } else { Test-Bad 'a fresh .env keeps no Redis placeholder' 'still present' 'gone' }
$redisValues = Get-Content $redisEnv | Where-Object { $_ -match '^REDIS_' } | ForEach-Object { ($_ -split '=', 2)[1] }
Test-Check 'the three Redis passwords are distinct' (($redisValues | Select-Object -Unique).Count) 3

# An install from before Redis had users: the lines are added, not refused.
'POSTGRES_PASSWORD=already-real' | Set-Content -Path $redisEnv -Encoding utf8
Set-AskwellRedisPasswords $redisEnv
foreach ($name in @('REDIS_API_PASSWORD', 'REDIS_WORKER_PASSWORD', 'REDIS_PROXY_PASSWORD')) {
    $value = ((Get-Content $redisEnv | Where-Object { $_ -match "^$name=" }) -split '=', 2)[1]
    Test-Check "an upgrade generates $name" $value.Length 64
}
$before = Get-Content $redisEnv -Raw
Set-AskwellRedisPasswords $redisEnv
Test-Check 'a second run changes no existing Redis password' (Get-Content $redisEnv -Raw) $before

# --- quarantine message ------------------------------------------------------------
$msg = Get-AskwellQuarantineMessage 'askwell-inference'
if ($msg -match 'askwell-inference') { Test-Ok 'quarantine message names the missing file' } else { Test-Bad 'quarantine message names the missing file' $msg 'askwell-inference' }
if ($msg -match 'quarantine') { Test-Ok 'quarantine message names the likely cause' } else { Test-Bad 'quarantine message names the likely cause' $msg 'quarantine' }

# --- M7-PACK-DEPLOY-142: stack + inference scheduled task helpers ------------------
# NOTE: this build host has no pwsh (PowerShell 7) to actually run this file
# (see docs/decisions.md, this date, and issue #606) — these assertions are
# written and reviewed, not executed here, the same disclosed gap as the rest
# of this suite's newest additions.
Test-Check 'stack task has a stable name' (Get-AskwellStackTaskName) 'AskwellStack'
Test-Check 'inference task has a stable, distinct name' (Get-AskwellInferenceTaskName) 'AskwellInference'

$stackArgs = Get-AskwellStackTaskArguments -ComposePath 'C:\Askwell\compose.yaml' -EnvPath 'C:\Askwell\.env'
if ($stackArgs -match 'compose -f "C:\\Askwell\\compose\.yaml" --env-file "C:\\Askwell\\\.env" up') {
    Test-Ok 'stack task arguments run compose against the real files'
} else {
    Test-Bad 'stack task arguments run compose against the real files' $stackArgs 'compose -f "..." --env-file "..." up'
}
if ($stackArgs -match '--abort-on-container-exit') {
    Test-Ok 'stack task arguments run compose in the foreground (--abort-on-container-exit)'
} else {
    Test-Bad 'stack task arguments run compose in the foreground (--abort-on-container-exit)' $stackArgs '--abort-on-container-exit'
}

$inferenceArgs = Get-AskwellInferenceTaskArguments -ScriptPath 'C:\Askwell\askwell-inference'
Test-Check 'inference task arguments name the real supervisor script' $inferenceArgs '"C:\Askwell\askwell-inference"'

Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ''
Write-Host "$script:Pass passed, $script:Fail failed"
if ($script:Fail -gt 0) { exit 1 }
exit 0
