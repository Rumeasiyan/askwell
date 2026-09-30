# Tests for the Windows installer's logic (M7-PACK-DEPLOY-140). See
# deploy/linux/install.test.sh for the pattern this follows.
#
# Tests lib.ps1's pure functions only - never a real winget, a real Podman
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
# (see docs/decisions.md, this date, and issue #606) - these assertions are
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

if ($stackArgs -match '--abort-on-container-exit --no-attach migrate') {
    Test-Ok 'stack task arguments do not let migrate''s successful exit stop the stack'
} else {
    Test-Bad 'stack task arguments do not let migrate''s successful exit stop the stack' $stackArgs '--no-attach migrate'
}

$inferenceArgs = Get-AskwellInferenceTaskArguments -ScriptPath 'C:\Askwell\askwell-inference'
Test-Check 'inference task arguments name the real supervisor script' $inferenceArgs '"C:\Askwell\askwell-inference"'

# --- database migration and purge (M9-FIX-DEPLOY-200, #698, #700) -----------
$migrationArgs = Get-AskwellMigrationArguments -ComposePath 'C:\Users\A B\Askwell\compose.yaml' -EnvPath 'C:\Users\A B\Askwell\.env'
Test-Check 'the migration runs compose''s own migrate service, paths quoted' $migrationArgs `
    'compose -f "C:\Users\A B\Askwell\compose.yaml" --env-file "C:\Users\A B\Askwell\.env" run --rm migrate'

$migrateLog = Join-Path $tmp 'migrate.log'
Set-Content -Path $migrateLog -Value @(
    'INFO  [alembic.runtime.migration] Running upgrade  -> a1, first',
    'INFO  [alembic.runtime.migration] Running upgrade a1 -> b2, second'
)
Test-Check 'a fresh schema reports each migration applied' (Get-AskwellMigrationsApplied $migrateLog) 2
Set-Content -Path $migrateLog -Value 'INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.'
Test-Check 'an upgrade with nothing pending reports zero applied' (Get-AskwellMigrationsApplied $migrateLog) 0
Test-Check 'a missing log reports zero applied' (Get-AskwellMigrationsApplied (Join-Path $tmp 'absent.log')) 0

$composeText = Get-Content (Join-Path $Here '..\..\compose.yaml') -Raw
$composeVolumes = ([regex]::Match($composeText, '(?ms)^volumes:\r?\n(.*)\z').Groups[1].Value -split '\r?\n' |
    Where-Object { $_ -match '^  ([a-z][a-z-]*):' } | ForEach-Object { 'askwell_' + $Matches[1] }) | Sort-Object
Test-Check 'AskwellVolumes names every volume compose.yaml declares' (($script:AskwellVolumes | Sort-Object) -join ' ') ($composeVolumes -join ' ')

# --- compose provider, kept credentials (#767, #765) --------------------------
Test-Check 'reads docker-compose''s version' (ConvertFrom-AskwellComposeVersion 'Docker Compose version v5.1.1') '5.1.1'
Test-Check 'reads it after podman''s provider banner' `
    (ConvertFrom-AskwellComposeVersion ">>>> Executing external compose provider <<<<`n`nDocker Compose version v2.20.2") '2.20.2'
Test-Check 'podman-compose is not read as a supported provider' (ConvertFrom-AskwellComposeVersion 'podman-compose version 1.5.0') $null
Test-Check 'docker-compose 5.1.1 meets the minimum' (Test-AskwellComposeMeetsMinimum 'Docker Compose version v5.1.1') $true
Test-Check 'docker-compose 2.19 is refused' (Test-AskwellComposeMeetsMinimum 'Docker Compose version v2.19.1') $false
Test-Check 'podman-compose is refused' (Test-AskwellComposeMeetsMinimum 'podman-compose version 1.5.0') $false
Test-Check 'no provider at all is refused' (Test-AskwellComposeMeetsMinimum '') $false
$keptEnv = Get-AskwellKeptEnvPath $tmp
Test-Check 'the kept .env lives in the data directory' (Split-Path -Parent $keptEnv) $tmp
Test-Check 'the kept .env is askwell.env, where the installer looks' (Split-Path -Leaf $keptEnv) 'askwell.env'

Remove-Item -Path $tmp -Recurse -Force -ErrorAction SilentlyContinue

# --- bundled images (M9-REL-DEPLOY-214) ----------------------------------------
$imgRoot = New-AskwellTempDir
Test-Check 'a source checkout has no bundled images' (@(Get-AskwellBundledImages $imgRoot)).Count 0
New-Item -ItemType Directory -Force -Path (Join-Path $imgRoot 'images') | Out-Null
Set-Content -Path (Join-Path $imgRoot 'images\redis.tar') -Value ''
Set-Content -Path (Join-Path $imgRoot 'images\api.tar') -Value ''
Set-Content -Path (Join-Path $imgRoot 'images\notes.txt') -Value ''
$images = @(Get-AskwellBundledImages $imgRoot)
Test-Check 'lists only *.tar' $images.Count 2
Test-Check 'sorted by name' (Split-Path -Leaf $images[0]) 'api.tar'
Remove-Item -Path $imgRoot -Recurse -Force -ErrorAction SilentlyContinue

# --- setup: WSL state and the one restart ---------------------------------------
Test-Check 'VirtualMachinePlatform enabled is ready' (Get-AskwellWslState 'Enabled') 'ready'
Test-Check 'enabled by this run still needs the restart' (Get-AskwellWslState 'Enabled' -EnabledThisRun) 'restart'
Test-Check 'enabled by this run but not enabled is missing' (Get-AskwellWslState 'Disabled' -EnabledThisRun) 'missing'
Test-Check 'enable pending means restart' (Get-AskwellWslState 'EnablePending') 'restart'
Test-Check 'disabled is missing, not restart' (Get-AskwellWslState 'Disabled') 'missing'
Test-Check 'payload removed is missing' (Get-AskwellWslState 'DisabledWithPayloadRemoved') 'missing'
Test-Check 'an unreadable state is missing, never restart' (Get-AskwellWslState '') 'missing'
Test-Check 'disable pending is missing, not restart' (Get-AskwellWslState 'DisablePending') 'missing'
$stage = Get-AskwellSetupStageDir 'C:\ProgramData'
Test-Check 'the stage lives in ProgramData' $stage 'C:\ProgramData\AskwellSetup'
$resume = Get-AskwellResumeCommand 'C:\Windows' $stage
if ($resume.Length -le 260) { Test-Ok "the RunOnce command fits in 260 characters ($($resume.Length))" } else { Test-Bad 'the RunOnce command fits in 260 characters' $resume.Length 260 }
Test-Check 'the RunOnce command, exactly' $resume '"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "C:\ProgramData\AskwellSetup\deploy\windows\setup\setup-bootstrap.ps1" -Resume'
if ($resume -match '-Resume$') { Test-Ok 'the RunOnce command resumes' } else { Test-Bad 'the RunOnce command resumes' $resume '...-Resume' }
if ($resume -match 'System32\\WindowsPowerShell') { Test-Ok 'the RunOnce command names the 64-bit PowerShell' } else { Test-Bad 'the RunOnce command names the 64-bit PowerShell' $resume 'System32' }

Test-Check 'models live where compose.yaml and the supervisor both look' (Get-AskwellModelsDir 'C:\Users\nimal') 'C:\Users\nimal\.local\share\askwell\models'

$pyDir = New-AskwellTempDir
Set-Content -Path (Join-Path $pyDir 'python.exe') -Value ''
Test-Check 'no pythonw.exe: the python.exe itself' (Get-AskwellWindowlessPython (Join-Path $pyDir 'python.exe')) (Join-Path $pyDir 'python.exe')
Set-Content -Path (Join-Path $pyDir 'pythonw.exe') -Value ''
Test-Check 'the supervisor runs windowless, as pythonw.exe' (Get-AskwellWindowlessPython (Join-Path $pyDir 'python.exe')) (Join-Path $pyDir 'pythonw.exe')
Remove-Item -Path $pyDir -Recurse -Force -ErrorAction SilentlyContinue

if (Test-AskwellProcessInPrefix 'C:\Users\n\AppData\Local\Askwell\app\askwell-shell.exe' 'C:\Users\n\AppData\Local\Askwell\app') { Test-Ok 'the running app of this install is found' } else { Test-Bad 'the running app of this install is found' $false $true }
if (-not (Test-AskwellProcessInPrefix 'D:\Other\Askwell\app\askwell-shell.exe' 'C:\Users\n\AppData\Local\Askwell\app')) { Test-Ok 'another copy of Askwell is left alone' } else { Test-Bad 'another copy of Askwell is left alone' $true $false }
if (-not (Test-AskwellProcessInPrefix 'C:\Users\n\AppData\Local\Askwell\app-old\askwell-shell.exe' 'C:\Users\n\AppData\Local\Askwell\app')) { Test-Ok 'a sibling folder with the same prefix is not this install' } else { Test-Bad 'a sibling folder with the same prefix is not this install' $true $false }

# --- setup: Python ------------------------------------------------------------
if (Test-AskwellStorePythonStub 'C:\Users\nimal\AppData\Local\Microsoft\WindowsApps\python.exe') { Test-Ok "the Store's placeholder python.exe is recognised" } else { Test-Bad "the Store's placeholder python.exe is recognised" $false $true }
if (-not (Test-AskwellStorePythonStub 'C:\Program Files\Python313\python.exe')) { Test-Ok 'a real Python is not taken for the placeholder' } else { Test-Bad 'a real Python is not taken for the placeholder' $true $false }
Test-Check 'Python comes from python.org, pinned' $script:AskwellPythonUrl 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.exe'
Test-Check 'a missing Python is explained' (Get-AskwellSetupCodeMeaning 25) 'Python could not be installed'

# --- setup: the failure report ------------------------------------------------
Test-Check 'a known code is explained' (Get-AskwellSetupCodeMeaning 22) 'Docker Compose could not be installed'
if ((Get-AskwellSetupCodeMeaning 7) -match 'install.ps1') { Test-Ok "install.ps1's own code points at the log" } else { Test-Bad "install.ps1's own code points at the log" (Get-AskwellSetupCodeMeaning 7) 'install.ps1' }
$raw = 'Copying to C:\Users\Nimal.Perera\AppData\Local\Temp on NIMAL-LAPTOP as nimal.perera; Podman 5.8.3'
$safe = Protect-AskwellReportText -Text $raw -UserProfile 'C:\Users\Nimal.Perera' -UserName 'nimal.perera' -ComputerName 'NIMAL-LAPTOP'
Test-Check 'profile and PC replaced in any case, account name as a word' $safe 'Copying to <profile>\AppData\Local\Temp on <pc> as <user>; Podman 5.8.3'
Test-Check 'a two-letter name is left alone, not stripped everywhere' (Protect-AskwellReportText -Text 'al alpha' -UserName 'al') 'al alpha'
Test-Check 'an account named like the product leaves the product name alone' (Protect-AskwellReportText -Text 'Askwell Setup ran as askwell; see github.com/Rumeasiyan/askwell-docs' -UserName 'askwell') 'Askwell Setup ran as <user>; see github.com/Rumeasiyan/askwell-docs'
Test-Check 'one name alone still works' (Protect-AskwellReportText -Text 'user nimal here' -UserName 'nimal') 'user <user> here'
$report = Format-AskwellSetupReport -Code 22 -Facts ([ordered]@{ 'Askwell version' = '1.2.3'; 'Windows' = 'Windows 11 Home' }) -Log "line one`r`nline two"
foreach ($want in @('send this file to whoever gave you Askwell', 'Result: code 22 - Docker Compose could not be installed', 'Askwell version: 1.2.3', 'Windows: Windows 11 Home', 'line two')) {
    if ($report.Contains($want)) { Test-Ok "the report says: $want" } else { Test-Bad "the report says: $want" 'missing' $want }
}
if ($report -notmatch '[^\x00-\x7F]') { Test-Ok 'the report is plain ASCII, readable in any Notepad' } else { Test-Bad 'the report is plain ASCII' 'non-ASCII' 'ASCII' }

Write-Host ''
Write-Host "$script:Pass passed, $script:Fail failed"
if ($script:Fail -gt 0) { exit 1 }
exit 0
