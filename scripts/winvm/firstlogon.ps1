# First sign-in of Askwell's Windows test VM (scripts/winvm.sh, #836).
# Turns on the OpenSSH server so the harness can copy Setup in and run it,
# and keeps the VM from sleeping. Deliberately changes nothing Askwell's
# Setup depends on: WSL, the Virtual Machine Platform, Podman and winget are
# left exactly as a new PC has them.
param([string]$Media)
$ErrorActionPreference = 'Continue'
$log = 'C:\askwell-vm-firstlogon.log'
Start-Transcript -Path $log -Append | Out-Null

Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
        -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
# The capability's own rule allows Private networks only, and QEMU's user
# network comes up as Public, so SSH timed out at the banner. Only QEMU's
# forwarded 127.0.0.1 port reaches this VM, so any profile is safe here.
Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Profile Any
# An administrator's key lives here, not in the profile, and must be
# readable only by Administrators and SYSTEM or sshd ignores it.
$keys = 'C:\ProgramData\ssh\administrators_authorized_keys'
Copy-Item -Path (Join-Path $Media 'authorized_keys') -Destination $keys -Force
& icacls.exe $keys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -PropertyType String -Force `
    -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' | Out-Null

& powercfg.exe /change standby-timeout-ac 0
& powercfg.exe /change monitor-timeout-ac 0
& powercfg.exe /hibernate off

Set-Content -Path 'C:\askwell-vm-ready.txt' -Value (Get-Date -Format o)
Stop-Transcript | Out-Null
