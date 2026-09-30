; Askwell-Setup-<version>.exe — the one-click Windows installer.
;
; Double-click, Install, done. It carries the whole Windows release tree (the
; shell, compose.yaml, deploy\, the container images), unpacks it to a
; temporary folder, and runs setup-bootstrap.ps1, which puts Podman, WSL and
; Docker Compose in place and then runs deploy\windows\install.ps1 unattended.
; install.ps1 does the real installation — the Start-menu entry, the
; Add/Remove Programs entry and the uninstaller — so this file duplicates none
; of it. Every line either script prints appears in the progress box.
;
; Built on Linux by .github/workflows/release.yml with makensis, which is why
; paths come in as defines rather than being hardcoded:
;   makensis -DVERSION=<v> -DSRCDIR=<release tree> -DOUTFILE=<exe> \
;            -DICON=<icon.ico> -DLICENSEFILE=<LICENSE> askwell-setup.nsi

Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !error "VERSION is required (-DVERSION=...)"
!endif
!ifndef SRCDIR
  !error "SRCDIR is required (-DSRCDIR=...)"
!endif
!ifndef OUTFILE
  !error "OUTFILE is required (-DOUTFILE=...)"
!endif

Name "Askwell ${VERSION}"
OutFile "${OUTFILE}"
; Installing Podman registers a WSL2 distribution, which needs an
; administrator (install.ps1 says the same). One UAC prompt up front is the
; one-click equivalent of "run this from an administrator PowerShell".
RequestExecutionLevel admin
; Per-file zlib, never /SOLID. The Windows payload is 2.1 GB uncompressed,
; one file of it (the API image) 1.7 GB, and a solid block that large fails
; in makensis with "Internal compiler error #12345: error mmapping file
; (573277500, 33554432) is out of range" — which is exactly how the first
; v0.9.1 release build failed. Measured on the real 0.9.0 Windows tree:
; /SOLID zlib fails; per-file zlib builds a 704 MB exe in 4.5 minutes;
; per-file lzma a 475 MB exe in 20 minutes. zlib keeps the release build
; fast and the download the same size as the zip.
SetCompressor zlib
InstallDir "$TEMP\AskwellSetup-${VERSION}"
ShowInstDetails show
BrandingText "Askwell ${VERSION}"

!ifdef ICON
  !define MUI_ICON "${ICON}"
!endif
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Install Askwell ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "Askwell is a personal AI over your own files and databases. It runs entirely on this PC, and nothing you add leaves it.$\r$\n$\r$\nSetup will install what Askwell needs to run (Podman, Docker Compose and the Windows Subsystem for Linux, if they are missing) and then Askwell itself. This takes several minutes and needs an internet connection for those components only.$\r$\n$\r$\nIf this PC has never used the Windows Subsystem for Linux, Windows needs to restart once. Setup then finishes by itself after you sign in.$\r$\n$\r$\nThis is a beta, and it is not code-signed. Windows may have warned you before this screen; that is expected."
!insertmacro MUI_PAGE_WELCOME
!ifdef LICENSEFILE
  !insertmacro MUI_PAGE_LICENSE "${LICENSEFILE}"
!endif
!insertmacro MUI_PAGE_INSTFILES
; A variable, set in the section: the finish page either says Askwell is
; installed or that one restart remains (code 30).
Var FinishTitle
!define MUI_FINISHPAGE_TITLE "$FinishTitle"
; Shown instead of MUI_FINISHPAGE_TEXT when the section sets the reboot flag,
; with MUI's own "Restart now" / "I will restart later" choice under it.
!define MUI_FINISHPAGE_TEXT_REBOOT "Everything else is installed. Windows needs to restart once to finish enabling the Windows Subsystem for Linux, which Askwell runs in.$\r$\n$\r$\nYou do not need to run Setup again. After the restart, sign in and a window opens by itself, finishes the install, and opens Askwell. It takes a few minutes."
!define MUI_FINISHPAGE_TEXT_REBOOTNOW "Restart now"
!define MUI_FINISHPAGE_TEXT_REBOOTLATER "I will restart later"
!define MUI_FINISHPAGE_TEXT "Askwell is in your Start menu. The first time it opens, it will offer to download its AI models (about 5.3 GB). After that, it works without an internet connection."
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

Section "Askwell"
  SetOutPath "$INSTDIR"
  DetailPrint "Unpacking Askwell..."
  File /r "${SRCDIR}/*"

  DetailPrint "Checking this PC and installing. This can take several minutes; the details appear below."
  ; The setup exe is a 32-bit program, and a 32-bit process that runs
  ; "powershell.exe" gets the 32-bit one, which Windows redirects from
  ; System32 to SysWOW64: wsl.exe is not there, so WSL looked missing on
  ; every PC (0.9.2). Sysnative is the alias a 32-bit process uses to reach
  ; the real System32, so this starts the 64-bit PowerShell.
  StrCpy $1 "$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
  IfFileExists "$1" +2 0
    StrCpy $1 "powershell.exe"
  nsExec::ExecToLog '"$1" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\deploy\windows\setup\setup-bootstrap.ps1" -Root "$INSTDIR"'
  Pop $0

  ${If} $0 == "0"
    StrCpy $FinishTitle "Askwell is installed"
    DetailPrint "Askwell is installed."
  ${ElseIf} $0 == "30"
    ; Not a failure: everything but WSL is in place, and the bootstrap has
    ; copied itself to %ProgramData%\AskwellSetup and registered a RunOnce
    ; entry that finishes the install after the restart. So no Abort, which
    ; would say "Installation Aborted": the finish page offers the restart.
    StrCpy $FinishTitle "One restart to finish"
    DetailPrint "One restart remains. Setup continues by itself after you sign in again."
    SetRebootFlag true
  ${Else}
    MessageBox MB_OK|MB_ICONEXCLAMATION "Askwell could not finish installing (code $0).$\r$\n$\r$\nSetup saved a report on your Desktop, named Askwell-Setup-report followed by today's date, and opened it in Notepad. Please send that file to whoever gave you Askwell: it tells them what went wrong, and holds none of your files."
    Abort "Setup did not finish (code $0). See the details above."
  ${EndIf}

  ; install.ps1 has copied everything it needs into Askwell's own folder;
  ; the unpacked release tree is no longer needed.
  SetOutPath "$TEMP"
  RMDir /r "$INSTDIR"
SectionEnd
