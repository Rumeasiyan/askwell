# Installing Askwell

**Askwell is not code-signed.** Linux installs normally. macOS and Windows will warn you the first time, and you have to tell them to proceed.

This page explains why, what you will see, and how to get past it — including how to check you are running what you think you are running.

---

## Why there is a warning

Signing certificates cost money every year — an Apple Developer enrolment and a Windows code-signing certificate. Askwell is free, has no revenue, and is maintained by one person. Until that changes, the builds are unsigned.

**What the warning does and does not mean.** It means the operating system cannot confirm *who* published this. It does not mean the file is damaged or malicious, and it is not a scan result — an unsigned build from a careful developer and an unsigned build from a hostile one look identical to Gatekeeper and SmartScreen.

**Which is exactly why the checksum below matters more than the warning does.** The bypass tells your machine to trust the file; the checksum is how *you* check it is the file we published.

---

## Verify what you downloaded — do this first

Every release publishes a `SHA256SUMS` file alongside the downloads: Linux (`askwell-<version>-linux-x86_64.tar.gz`), Windows (`Askwell-Setup-<version>.exe`, or the same files as `askwell-<version>-windows-x86_64.zip`) and macOS (`askwell-<version>-macos-arm64.tar.gz`). Compare before you unpack anything.

**Linux and macOS**

```
shasum -a 256 askwell-<version>-<platform>-<arch>.tar.gz
```

**Windows (PowerShell)**

```
Get-FileHash Askwell-Setup-<version>.exe -Algorithm SHA256
```

The value must match the line for your file in `SHA256SUMS` on the release page. **If it does not match, stop.** Do not run it, and open an issue — a mismatch means the file was altered between our build and your disk, and that is worth knowing about.

---

## Linux

No warning, nothing to bypass. Unpack the download and run its installer from a terminal:

```
tar -xzf askwell-<version>-linux-x86_64.tar.gz
askwell-<version>-linux-x86_64/deploy/linux/install.sh
```

It installs what is missing, asking for your password once to do so: Podman; Docker Compose, which Askwell uses to run its containers through Podman; and the OpenMP runtime (`libgomp`), which Askwell's AI needs. On Fedora, Ubuntu and distributions built on Ubuntu it offers to install all three for you. On other distributions it stops before copying anything and tells you what to install yourself — for Docker Compose, version 2.20 or newer (docs.docker.com/compose/install/linux). It then loads Askwell's containers from the download, sets up Askwell's database, and opens the Askwell window. Afterwards Askwell is in your applications menu.

---

## macOS

macOS will refuse the first launch: **"Askwell cannot be opened because the developer cannot be verified."**

1. Unpack the download and run its installer from Terminal:

   ```
   tar -xzf askwell-<version>-macos-arm64.tar.gz
   askwell-<version>-macos-arm64/deploy/macos/install.sh
   ```

   It installs Podman and Docker Compose with Homebrew if they are missing, loads Askwell's containers, sets up Askwell's database, places Askwell in Applications and tries to open it.
2. You will get the refusal. Click **Done**.
3. Open **System Settings → Privacy & Security**, scroll to Security. There is a line saying Askwell was blocked, with an **Open Anyway** button.
4. Click it, then confirm.

You do this once. Afterwards it opens normally.

> Older instructions tell you to right-click the app and choose Open. **That shortcut no longer works on recent macOS versions** — the System Settings route above is the one that does.

If you would rather do it from a terminal, this removes the quarantine flag the browser attached to the download:

```
xattr -d com.apple.quarantine /Applications/Askwell.app
```

Only run that after the checksum matches. It is the same decision as clicking Open Anyway, made faster.

---

## Windows

**Download `Askwell-Setup-<version>.exe` and double-click it.** Verify its checksum first, as above.

**Askwell needs Windows 11, version 22H2 or newer.** On an older Windows, Setup says so and installs nothing.

1. Windows asks for administrator permission. Setup needs it once, to install Podman, which runs Askwell's local services.
2. Click **Install**. Setup checks this PC and installs anything Askwell needs that is missing: Podman, the Windows Subsystem for Linux, Docker Compose, Python and Microsoft's Visual C++ runtime. The Visual C++ runtime is checked to be signed by Microsoft before it runs; one that is not is refused, and Setup stops with code 28. It then installs Askwell itself, and every step is shown as it happens. This takes several minutes. Only those components come from the internet; nothing of yours is sent anywhere.
3. When it finishes, Askwell is in your Start menu and in *Add or remove programs*.

Setup changes one Windows setting, and its log says so. It sets WSL's networking to *mirrored* (`networkingMode=mirrored` under `[wsl2]` in `%USERPROFILE%\.wslconfig`), which is how Askwell's services reach its AI on your PC. It keeps everything else in that file. If WSL was running, it restarts WSL once, which also stops any other Linux distribution you had open.

Two things Setup cannot do by itself, and tells you when they happen:

- **Windows needs a restart** the first time it enables the Windows Subsystem for Linux. Restart, then run Setup again, and it carries on from there.
- **CPU virtualisation is off** in the PC's firmware. Setup names the setting to turn on. It is in the BIOS/UEFI, not in Windows, so it has to be done by hand.

**Without Setup.** The zip holds the same files. Unpack it (right-click → **Extract All**), open PowerShell in the unpacked folder, and run:

```
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
```

`install.ps1` does not change your WSL settings. If mirrored networking is not set, it warns you, and Askwell will not be able to answer until you set it.

`-ExecutionPolicy Bypass` applies to this one command only. Windows otherwise refuses to run a script that came from the internet. Run this way, the installer stops after installing Podman or Docker Compose and asks you to open a new PowerShell and run it again, because a running session cannot see a program installed during it. Setup avoids that.

SmartScreen will show **"Windows protected your PC"** with **Don't run** as the default button.

1. Click **More info** — the small link above the buttons, which is easy to miss.
2. Click **Run anyway**.

You do this once for a given version. A new version may warn again until it accrues its own reputation.

---

## The honest part

Telling you to click past a security warning is teaching you to click past security warnings, and that is a real cost — not a formality we are waving through. It is the reason the checksum section is above the bypass and not below it.

**Verify the checksum.** That is the check that actually protects you here. The bypass only tells your computer to stop asking.

When Askwell is signed, this page becomes much shorter.
