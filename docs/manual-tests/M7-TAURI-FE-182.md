# Manual test — M7-TAURI-FE-182, native file dialogs

**Ticket:** `M7-TAURI-FE-182` — native directory/file dialogs wired into root registration, relocating a moved document, and the add-source screen's browse alternative, plus the scoped filesystem reads (`list_dir`, `read_head`) that let a picked folder be walked and detected the same way a browser drop already is.
**Version under test:** `0.7.6`
**Time:** about 25 minutes.
**Who can run it:** a machine with the Rust toolchain, the system webview libraries (`webkit2gtk4.1-devel`/`libwebkit2gtk-4.1-dev`, `gtk3-devel`, `atk-devel`, `cairo-gobject-devel` on Linux, or their Windows/macOS equivalents) **and root/administrator access to install them**, and Podman. **Neither is true of the session that wrote this document** (issue #497) — `cargo check` fails on the same `gdk-pixbuf-sys`/`pkg-config` gap that ticket already named, before reaching any code this ticket adds, and there is no `sudo` available to close it. This document is therefore written from the code and from `rustc --edition 2021 --emit=metadata` (parses every file with zero syntax errors; every remaining error is an expected unresolved-crate one, since no dependency is linked) rather than from an actual run, and every step below is unverified until a session with those libraries runs it.

**What is being checked.** `web/src-tauri/src/main.rs`: five new commands (`pick_folder`, `pick_file`, `pick_files`, `list_dir`, `read_head`), each granted to the shell's one origin in `capabilities/default.json` and each refusing a path outside `AllowedRoots` — the set of paths a dialog has actually returned this session (issue #580's fix). `web/lib/native.ts`'s thin IPC wrappers, and `web/lib/selection.ts`'s `fromNativeFolder`/`fromNativeFiles`, which walk a picked folder with `list_dir` the same way `fromDrop` walks a browser drop with the DOM's directory reader. Three screens: `components/settings/folders.tsx` (root registration), `components/documents/viewer-shared.tsx`'s `MovedFileNotice` (relocation), `components/add/add-screen.tsx`'s `FilesRoute` (browse alternative).

**Where this stops on purpose.** No change to the roots registry, hash verification, or the moved/deleted distinction — every dialog hands its path to the exact same request a typed path already produced. No folder watching. No bulk relocation of a whole moved root. Multi-select of several roots at once is not supported.

---

## Before you start

```
cd ~/external/quantum-plus/askwell
podman compose up -d
scripts/dev.sh db upgrade head
scripts/dev.sh tauri build
```

**You should see:** the same clean `cargo build --release` this ticket's dependency (`M7-TAURI-DEPLOY-181`) already required, now also compiling `rfd`'s dialog backend for this platform, ending with an `askwell-shell` binary under `web/src-tauri/target/release/`.

Launch it:

```
web/src-tauri/target/release/askwell-shell
```

---

## Part A — root registration

### 1. Open Settings → Folders and click **Choose a folder**

**You should see:** the platform's own directory dialog — the one every other application on this machine uses, not a text field. Navigate to a real folder containing a few PDFs and confirm it.

### 2. Watch the folder register

**You should see:** the chosen folder appears in the list exactly as a typed path would, and (on macOS only) if the folder was outside the few areas the app is allowed into by default, the system's own permission prompt appeared first, with Askwell's own explanatory line ("macOS is the one asking here…") shown beside the **Choose a folder** button.

### 3. Click **Choose a folder** again and cancel the dialog without picking anything

**You should see:** nothing changes — no new row, no error, the screen exactly as it was.

### 4. Add a source from that folder (Add a source → Files → Choose a folder)

**You should see:** the platform's directory dialog again; picking the same folder lists every file inside it (walked via `list_dir`), each one detected from its real first bytes (`read_head`) exactly as a browser-dropped file would be, and indexing begins once queued.

---

## Part B — relocating a moved document

### 5. Rename or move a file already indexed from Part A's folder, on disk, outside Askwell

### 6. Open that document's citation in the source viewer

**You should see:** the moved-file notice, naming the missing path, with a **Choose the file** button ahead of the typed field.

### 7. Click **Choose the file** and pick the renamed file

**You should see:** the viewer reopens on the relocated content — the hash matched.

### 8. Repeat relocation, but pick a *different* document by mistake

**You should see:** refused by name — the hash mismatch, not a silent repoint.

---

## Part C — browsing for files (the add-source screen's alternative to dropping)

### 9. Add a source → Files → **Choose files** (not the folder button)

**You should see:** the platform's own multi-file dialog, not the browser file input. Pick two or three files; both register with their real sizes.

---

## Part D — the scoping this ticket's own review required (issue #580)

### 10. With the shell's devtools or a script, attempt to call `list_dir` or `read_head` on a path never returned by a dialog in this session (e.g. `/etc/passwd`)

**You should see:** a refusal — `"That path is outside every folder or file you chose."` — not the file's contents. This is the fix for issue #580: the IPC layer itself now checks, rather than trusting whatever path string the webview sends.

### 11. Run the shell's own unit tests

```
scripts/dev.sh tauri test
```

**You should see:** `native_command_tests`' five tests pass — a path under a granted root is allowed, a path outside every granted root is refused, `read_head` returns only the requested byte count, and `list_dir` reports both a file and a subfolder correctly.

---

## Part E — the frontend's own tests (these *did* run this session)

```
cd web && npm test
```

**You should see:** `lib/native.test.ts` (18 tests: `isNative`/`isMacOS`, every command wrapper against a faked `globalThis.__TAURI_INTERNALS__`, both path-separator helpers) and `lib/selection.test.ts` (6 tests: `fromNativeFolder` walking a fake nested filesystem with folder counting and a lazy `head()`, `fromNativeFiles` mapping picks including the empty/cancelled case) pass alongside the existing 411.

---

## Known gaps

- **Not run end-to-end this session.** No system webview libraries and no `sudo` to install them (issue #497, still open) — Parts A through D above are unverified walkthroughs, written from the code, not confirmed behaviour. Part E's frontend tests did run and did pass.
- **Windows/macOS path translation across the container mount boundary is unverified** (issue #498) — this ticket does not touch that translation; a native dialog's own path format reaching `covering()`/`register()` correctly on those platforms is exactly what #498 already names as unverified, and still is.
- **No stat-based size for a native folder walk's root entry** — only files carry a real `size`; the synthetic root entry `fromNativeFolder` builds for `flatten()` does not, which is correct (a folder has no byte size to report) but worth knowing if `flatten`'s output is ever inspected directly rather than through `Selection.files`.
