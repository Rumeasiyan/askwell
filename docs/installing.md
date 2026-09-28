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

Every release publishes a `SHA256SUMS` file alongside the downloads — one for each of Linux (`askwell-<version>-linux-x86_64.tar.gz`), Windows (`askwell-<version>-windows-x86_64.zip`) and macOS (`askwell-<version>-macos-arm64.tar.gz`). Compare before you unpack anything.

**Linux and macOS**

```
shasum -a 256 askwell-<version>-<platform>-<arch>.tar.gz
```

**Windows (PowerShell)**

```
Get-FileHash askwell-<version>-windows-x86_64.zip -Algorithm SHA256
```

The value must match the line for your file in `SHA256SUMS` on the release page. **If it does not match, stop.** Do not run it, and open an issue — a mismatch means the file was altered between our build and your disk, and that is worth knowing about.

---

## Linux

No warning, nothing to bypass. Unpack the download and run its installer from a terminal:

```
tar -xzf askwell-<version>-linux-x86_64.tar.gz
askwell-<version>-linux-x86_64/deploy/linux/install.sh
```

It installs Podman if it is missing (asking for your password to do so), and Docker Compose, which Askwell uses to run its containers through Podman. On Fedora it offers to install Docker Compose for you. On other distributions it stops before copying anything and tells you to install Docker Compose 2.20 or newer yourself (docs.docker.com/compose/install/linux). It then loads Askwell's containers from the download, sets up Askwell's database, and opens the Askwell window. Afterwards Askwell is in your applications menu.

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

Unpack the zip (right-click → **Extract All**), then open PowerShell in the unpacked folder and run its installer:

```
powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
```

`-ExecutionPolicy Bypass` applies to this one command only; Windows otherwise refuses to run a script that came from the internet. The installer checks virtualisation and installs Podman if it is missing. If Docker Compose is missing, it stops and names the command that installs it (`winget install -e --id Docker.DockerCompose`); run that, open a new PowerShell, and run the installer again. It then loads Askwell's containers, sets up Askwell's database and opens the Askwell window.

SmartScreen will show **"Windows protected your PC"** with **Don't run** as the default button.

1. Click **More info** — the small link above the buttons, which is easy to miss.
2. Click **Run anyway**.

You do this once for a given version. A new version may warn again until it accrues its own reputation.

---

## The honest part

Telling you to click past a security warning is teaching you to click past security warnings, and that is a real cost — not a formality we are waving through. It is the reason the checksum section is above the bypass and not below it.

**Verify the checksum.** That is the check that actually protects you here. The bypass only tells your computer to stop asking.

When Askwell is signed, this page becomes much shorter.
