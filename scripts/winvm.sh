#!/usr/bin/env bash
# Askwell's Windows test VM (#836): a real Windows 11 on this machine, so
# Windows Setup is tested end to end, restart included, before a release
# instead of on testers' PCs.
#
#   scripts/winvm.sh create ISO     unattended install from a Windows 11 ISO,
#                                   then a clean snapshot. About an hour.
#   scripts/winvm.sh start          boot (from the current disk)
#   scripts/winvm.sh stop           shut Windows down and wait
#   scripts/winvm.sh reset          back to the clean snapshot (VM stopped)
#   scripts/winvm.sh ssh [CMD...]   PowerShell in the VM, as its administrator
#   scripts/winvm.sh put SRC DEST   copy a file in
#   scripts/winvm.sh get SRC DEST   copy a file out
#   scripts/winvm.sh screenshot OUT.png
#   scripts/winvm.sh status
#
# Needs only what Fedora already has here: KVM with nested virtualisation
# (WSL2 inside the VM is itself a VM), QEMU, swtpm and the Secure Boot OVMF.
# No root. Everything lives in $ASKWELL_WINVM_DIR, outside the repo; the
# VM's password and SSH key are generated there and never committed (C8).
#
# Memory: 8 GB by default (ASKWELL_WINVM_MEM). Do not start it while an eval
# is running; the two together do not fit on this machine.
#
# The VM reaches the internet through QEMU's user networking, as a new PC
# would, because Setup installs Podman, Compose and WSL from the network.
# Only SSH is forwarded in, and only on 127.0.0.1.
set -euo pipefail

VM_DIR="${ASKWELL_WINVM_DIR:-$HOME/.local/share/askwell-winvm}"
MEM="${ASKWELL_WINVM_MEM:-8G}"
CPUS="${ASKWELL_WINVM_CPUS:-4}"
SSH_PORT="${ASKWELL_WINVM_SSH_PORT:-2222}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVMF_CODE=/usr/share/edk2/ovmf/OVMF_CODE.secboot.fd
OVMF_VARS=/usr/share/edk2/ovmf/OVMF_VARS.secboot.fd
DISK="$VM_DIR/disk.qcow2"
QMP="$VM_DIR/qmp.sock"
TPM_DIR="$VM_DIR/tpm"
KEY="$VM_DIR/vm_ed25519"
SNAP="$VM_DIR/clean"

say() { printf '==> %s\n' "$*"; }
die() { printf 'winvm: %s\n' "$*" >&2; exit 1; }

running() { [ -S "$QMP" ] && python3 "$HERE/winvm/qmp.py" "$QMP" status >/dev/null 2>&1; }

ssh_vm() {
  ssh -i "$KEY" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR -o ConnectTimeout=5 askwell@127.0.0.1 "$@"
}

start_tpm() {
  mkdir -p "$TPM_DIR"
  pkill -f "[s]wtpm socket --tpmstate dir=$TPM_DIR" 2>/dev/null || true
  swtpm socket --tpmstate dir="$TPM_DIR" --ctrl type=unixio,path="$TPM_DIR/sock" \
    --tpm2 --daemon --log file="$TPM_DIR/swtpm.log"
  for _ in $(seq 50); do [ -S "$TPM_DIR/sock" ] && return 0; sleep 0.1; done
  die "swtpm did not start"
}

manufacture_tpm() {
  # What libvirt does before a TPM's first boot: create the endorsement key
  # and its certificates. An unmanufactured swtpm is attached and answers,
  # but Windows 11 Setup still reports "The PC must support TPM 2.0". The
  # certificate authority is the VM's own, under $VM_DIR, because the
  # system one in /var/lib needs root.
  mkdir -p "$TPM_DIR"
  XDG_CONFIG_HOME="$VM_DIR/xdg" swtpm_setup --create-config-files skip-if-exist >/dev/null
  XDG_CONFIG_HOME="$VM_DIR/xdg" swtpm_setup --tpm2 --tpmstate "$TPM_DIR" --create-ek-cert \
    --create-platform-cert --lock-nvram --overwrite --pcr-banks sha256 >/dev/null
}

boot() {  # boot [extra qemu args...]
  running && die "already running"
  [ -e /dev/kvm ] || die "no /dev/kvm"
  start_tpm
  rm -f "$QMP"
  qemu-system-x86_64 -name askwell-winvm -enable-kvm \
    -machine q35,smm=on -cpu host -smp "$CPUS" -m "$MEM" \
    -global driver=cfi.pflash01,property=secure,value=on \
    -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
    -drive if=pflash,format=raw,file="$VM_DIR/vars.fd" \
    -chardev socket,id=chrtpm,path="$TPM_DIR/sock" -tpmdev emulator,id=tpm0,chardev=chrtpm \
    -device tpm-crb,tpmdev=tpm0 \
    -drive file="$DISK",format=qcow2,if=ide,index=0 \
    -netdev user,id=n0,hostfwd=tcp:127.0.0.1:"$SSH_PORT"-:22 -device e1000e,netdev=n0 \
    -device qemu-xhci -device usb-tablet \
    -display none -vnc 127.0.0.1:5 -qmp unix:"$QMP",server,nowait \
    -pidfile "$VM_DIR/qemu.pid" -daemonize "$@"
}

wait_ssh() {  # wait_ssh SECONDS
  local deadline=$((SECONDS + $1))
  while [ $SECONDS -lt $deadline ]; do
    ssh_vm 'exit 0' >/dev/null 2>&1 && return 0
    sleep 15
  done
  return 1
}

stop_vm() {
  running || return 0
  python3 "$HERE/winvm/qmp.py" "$QMP" powerdown || true
  for _ in $(seq 120); do running || break; sleep 2; done
  if running; then kill "$(cat "$VM_DIR/qemu.pid")" 2>/dev/null || true; sleep 2; fi
  pkill -f "[s]wtpm socket --tpmstate dir=$TPM_DIR" 2>/dev/null || true
  rm -f "$QMP"
}

save_clean() {
  rm -rf "$SNAP"; mkdir -p "$SNAP"
  qemu-img snapshot -d clean "$DISK" 2>/dev/null || true
  qemu-img snapshot -c clean "$DISK"
  cp "$VM_DIR/vars.fd" "$SNAP/vars.fd"
  cp -r "$TPM_DIR" "$SNAP/tpm"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  create)
    iso="${1:?usage: winvm.sh create ISO}"
    [ -f "$iso" ] || die "no ISO at $iso"
    [ -e "$DISK" ] && die "$DISK exists; remove $VM_DIR to start over"
    mkdir -p "$VM_DIR"; chmod 700 "$VM_DIR"
    [ -f "$VM_DIR/credentials" ] || {
      printf 'ASKWELL_WINVM_PASSWORD=%s\n' "$(head -c 18 /dev/urandom | base64 | tr -d '/+=')" > "$VM_DIR/credentials"
      chmod 600 "$VM_DIR/credentials"
    }
    # shellcheck disable=SC1091
    . "$VM_DIR/credentials"
    [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N '' -C askwell-winvm -f "$KEY"
    cp "$OVMF_VARS" "$VM_DIR/vars.fd"
    manufacture_tpm
    qemu-img create -q -f qcow2 "$DISK" 80G
    media="$VM_DIR/media"; rm -rf "$media"; mkdir -p "$media"
    sed "s|@@PASSWORD@@|$ASKWELL_WINVM_PASSWORD|g" "$HERE/winvm/autounattend.xml.in" > "$media/autounattend.xml"
    cp "$HERE/winvm/firstlogon.ps1" "$media/firstlogon.ps1"
    cp "$KEY.pub" "$media/authorized_keys"
    genisoimage -quiet -J -r -V UNATTEND -o "$VM_DIR/unattend.iso" "$media"
    rm -rf "$media"
    say "installing Windows unattended (typically 20-40 minutes)"
    boot -drive file="$iso",media=cdrom,index=1 -drive file="$VM_DIR/unattend.iso",media=cdrom,index=2
    # The Windows DVD asks "Press any key to boot from CD or DVD" for a few
    # seconds; answer it.
    for _ in $(seq 20); do python3 "$HERE/winvm/qmp.py" "$QMP" keys ret >/dev/null 2>&1 || true; sleep 1; done
    wait_ssh 5400 || die "no SSH after 90 minutes; look: winvm.sh screenshot /tmp/w.png, or VNC 127.0.0.1:5905"
    for _ in $(seq 60); do
      ssh_vm 'Test-Path C:\askwell-vm-ready.txt' 2>/dev/null | grep -q True && break; sleep 10
    done
    say "Windows is up; saving the clean snapshot"
    stop_vm
    save_clean
    say "done: $VM_DIR (clean snapshot saved)"
    ;;
  start) boot; wait_ssh 900 || die "no SSH after 15 minutes"; say "up (ssh on 127.0.0.1:$SSH_PORT)" ;;
  stop) stop_vm; say "stopped" ;;
  reset)
    running && die "stop it first"
    qemu-img snapshot -a clean "$DISK"
    cp "$SNAP/vars.fd" "$VM_DIR/vars.fd"
    rm -rf "$TPM_DIR"; cp -r "$SNAP/tpm" "$TPM_DIR"
    say "back to the clean snapshot"
    ;;
  ssh) ssh_vm "$@" ;;
  put) scp -i "$KEY" -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "$1" "askwell@127.0.0.1:$2" ;;
  get) scp -i "$KEY" -P "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "askwell@127.0.0.1:$1" "$2" ;;
  screenshot) python3 "$HERE/winvm/qmp.py" "$QMP" screenshot "$(realpath -m "$1")" ;;
  status) if running; then echo "running"; else echo "stopped"; fi ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
