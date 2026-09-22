// Prevents an extra console window from opening on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashSet;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::webview::NewWindowResponse;
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder};

mod supervisor;

/// The version baked in by `build.rs` from the repo-root `VERSION` file — see
/// that file's docstring for why the shell never hand-copies this number.
const SHELL_VERSION: &str = env!("ASKWELL_SHELL_VERSION");

/// `ASKWELL_PORT` in `compose.yaml` publishes the API on `127.0.0.1` at this
/// port by default (`docs/architecture.md` §5). The shell reads the same
/// variable so a developer who has moved the port with `ASKWELL_PORT=...`
/// does not also have to reconfigure the shell.
fn api_origin() -> String {
    let port = std::env::var("ASKWELL_PORT").unwrap_or_else(|_| "8000".to_string());
    format!("http://127.0.0.1:{port}")
}

fn main() {
    let api_origin = api_origin();

    let builder = tauri::Builder::default()
        // Registered before anything else creates a window: a second launch
        // hands its arguments to the first process and exits immediately,
        // rather than racing it to open a window of its own (this ticket's
        // "second launch while one is running" edge case).
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        // Size and position persist across launches on its own (window-state
        // plugin, `on_window_ready`/`on_window_event`), and only restores a
        // saved position when a monitor still exists there — otherwise it
        // leaves placement to the OS default rather than opening off-screen.
        .plugin(tauri_plugin_window_state::Builder::default().build())
        // `M7-TAURI-FE-182`: the set of paths a dialog has actually returned
        // to this session. `list_dir`/`read_head` refuse anything outside it
        // — the IPC boundary is the enforcement point named in
        // `docs/decisions.md`, and it did none of this before (issue #580).
        .manage(AllowedRoots(Mutex::new(HashSet::new())))
        .invoke_handler(tauri::generate_handler![
            pick_folder,
            pick_files,
            pick_file,
            list_dir,
            read_head,
            open_supervision_window,
            supervision_status,
            supervision_control,
            supervision_log_location
        ])
        .setup(move |app| {
            let launch_count = record_launch(app.handle());
            log_event(app.handle(), "shell_start", None);
            let _ = launch_count; // no display surface yet (issue #482) — counted, not shown

            let start_url = starting_page_url(&api_origin);
            let navigation_origin = api_origin.clone();

            let window =
                WebviewWindowBuilder::new(app, "main", WebviewUrl::App(start_url.into()))
                    .title("Askwell")
                    .inner_size(1280.0, 800.0)
                    .min_inner_size(960.0, 640.0)
                    .center()
                    // C1/C7: the window is never a general browser. The only
                    // places it may ever point are its own bundled starting
                    // page and the local API's own origin — nothing else,
                    // regardless of what a document, a clicked citation link,
                    // or a popup attempt asks for.
                    .on_navigation(move |url| is_allowed_navigation(url, &navigation_origin))
                    // `window.open()` / `target="_blank"` do not go through
                    // `on_navigation` — this is the separate hook WRY exposes
                    // for it, and a denied request here is the whole reason
                    // clicking an external link in retrieved content cannot
                    // spawn a second window that on_navigation never sees.
                    .on_new_window(|_url, _features| NewWindowResponse::Deny)
                    .build();

            // Reported once, uniformly, by the final match below rather than
            // here — `setup` errors and `build` errors both funnel through
            // the same `tauri::Error`, and showing the dialog in both places
            // would just double it.
            window?;

            spawn_api_version_watcher(app.handle().clone(), api_origin.clone());

            // `M7-TAURI-DEPLOY-183`: the shell brings up the container stack
            // and the native inference process, watches both, and stops both
            // on quit — see `supervisor.rs`. Started after the window exists
            // because it reports into that window while things come up.
            let install_root = supervisor::resolve_install_root();
            let run_dir = install_root.join(".run");
            let supervisor_config = supervisor::SupervisorConfig {
                install_root,
                run_dir,
                container_binary: std::env::var("ASKWELL_CONTAINER_BINARY")
                    .unwrap_or_else(|_| "podman".to_string()),
                api_origin: api_origin.clone(),
            };
            let supervisor_handle = supervisor::start(app.handle().clone(), supervisor_config);
            app.manage(supervisor_handle);

            // `M7-PACK-FE-143`: the one "desktop entry point" this ticket asks
            // for — a native application menu item, present in the window's
            // own chrome the moment the window exists, whether that window is
            // still showing `starting.html` or has handed off to the real
            // application. A menu lives at the OS level rather than inside
            // page content, so it works even if the page itself never loads.
            let supervision_item =
                MenuItem::with_id(app, "open_supervision", "Supervision…", true, None::<&str>)?;
            let askwell_menu = Submenu::with_id_and_items(
                app,
                "askwell",
                "Askwell",
                true,
                &[
                    &supervision_item,
                    &PredefinedMenuItem::separator(app)?,
                    &PredefinedMenuItem::quit(app, None)?,
                ],
            )?;
            let menu = Menu::with_items(app, &[&askwell_menu])?;
            app.set_menu(menu)?;
            app.on_menu_event(move |app_handle, event| {
                if event.id() == "open_supervision" {
                    if let Err(error) = open_supervision_window_impl(app_handle) {
                        eprintln!("askwell-shell: could not open the supervision window: {error}");
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!());

    match builder {
        Ok(app) => {
            app.run(|app_handle, event| {
                if let tauri::RunEvent::ExitRequested { .. } = event {
                    log_event(app_handle, "shell_stop", None);
                    // Blocking here delays `Exit` until both halves have
                    // stopped — this ticket's "quitting the shell leaves no
                    // container and no process running", not merely
                    // "eventually".
                    app_handle
                        .state::<std::sync::Arc<supervisor::Handle>>()
                        .stop_and_wait();
                }
            });
        }
        Err(error) => {
            report_webview_unavailable(&error);
            std::process::exit(1);
        }
    }
}

/// `starting.html` (bundled, offline) rather than the API origin directly —
/// this ticket's edge case: the API is not up yet when the window opens, and
/// the window must show Askwell's own starting state, not the webview's
/// connection-refused page. The page polls `{api}/health` itself and hands
/// off to the real application the moment it answers.
fn starting_page_url(api_origin: &str) -> String {
    format!("starting.html?api={}", urlencode(api_origin))
}

fn urlencode(value: &str) -> String {
    value
        .bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'.' | b'_' | b'~' => {
                (b as char).to_string()
            }
            other => format!("%{other:02X}"),
        })
        .collect()
}

/// Allow only the bundled asset page (the shell's own starting/loading
/// content, served from Tauri's internal asset protocol) and the local API's
/// own origin. Everything else — an external site, a link inside retrieved
/// document content, a redirect to a different host — is refused. Covers
/// same-window navigation; `on_new_window` (set alongside this on the window
/// builder) covers `window.open()`/`target="_blank"`, which does not raise
/// this callback.
fn is_allowed_navigation(url: &Url, api_origin: &str) -> bool {
    let is_asset_origin = matches!(url.scheme(), "tauri" | "asset")
        || url.host_str() == Some("tauri.localhost")
        || url.host_str() == Some("ipc.localhost");

    if is_asset_origin {
        return true;
    }

    // `Origin` equality, not scheme+host alone: a bare host match lets any
    // other local process listening on 127.0.0.1 on a *different* port pass
    // this check (issue #481). `url::Origin` folds in the port (using each
    // scheme's default when absent), so http://127.0.0.1:9999 no longer
    // matches an API origin of http://127.0.0.1:8000.
    match Url::parse(api_origin) {
        Ok(allowed) => url.origin() == allowed.origin(),
        Err(_) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allows_same_origin() {
        let url = Url::parse("http://127.0.0.1:8000/answer/123").unwrap();
        assert!(is_allowed_navigation(&url, "http://127.0.0.1:8000"));
    }

    #[test]
    fn rejects_same_host_different_port() {
        let url = Url::parse("http://127.0.0.1:9999/anything").unwrap();
        assert!(!is_allowed_navigation(&url, "http://127.0.0.1:8000"));
    }

    #[test]
    fn rejects_external_host() {
        let url = Url::parse("https://example.com/").unwrap();
        assert!(!is_allowed_navigation(&url, "http://127.0.0.1:8000"));
    }

    #[test]
    fn allows_tauri_asset_origin() {
        let url = Url::parse("tauri://localhost/starting.html").unwrap();
        assert!(is_allowed_navigation(&url, "http://127.0.0.1:8000"));
    }
}

/// The system webview is missing or too old to create a window at all — this
/// ticket's edge case: report it by name with what to install, rather than a
/// blank window or a raw Rust panic.
fn report_webview_unavailable(error: &tauri::Error) {
    let guidance = if cfg!(target_os = "linux") {
        "Askwell needs WebKitGTK to run. Install it and try again:\n\
         \u{2022} Fedora: sudo dnf install webkit2gtk4.1\n\
         \u{2022} Debian/Ubuntu: sudo apt install libwebkit2gtk-4.1-0"
    } else if cfg!(target_os = "windows") {
        "Askwell needs the Microsoft Edge WebView2 Runtime to run. Install it from \
         Microsoft's website and try again."
    } else {
        "Askwell could not create its application window."
    };

    eprintln!("askwell-shell: could not start: {error}\n{guidance}");

    let _ = rfd::MessageDialog::new()
        .set_title("Askwell can't start")
        .set_description(&format!("{guidance}\n\nDetail: {error}"))
        .set_level(rfd::MessageLevel::Error)
        .show();
}

/// Polls the API's own `/health` (already required to report its `version`,
/// `api/src/askwell/health.py`) until it answers, then logs the connection
/// once with that version attached — satisfying "shell start and stop are
/// logged with the version of the shell and of the API it connected to"
/// without granting the webview any Tauri command (`capabilities/default.json`
/// stays empty). A background thread rather than the async runtime Tauri
/// already runs: one blocking poll loop for the whole process lifetime is not
/// worth a second executor.
fn spawn_api_version_watcher(app: tauri::AppHandle, api_origin: String) {
    std::thread::spawn(move || {
        let url = format!("{api_origin}/health");
        loop {
            if let Ok(mut response) = ureq::get(url.as_str()).call() {
                if let Ok(body) = response.body_mut().read_json::<serde_json::Value>() {
                    let version = body
                        .get("version")
                        .and_then(|v| v.as_str())
                        .map(String::from);
                    log_event(&app, "shell_api_connected", version.as_deref());
                    return;
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(750));
        }
    });
}

/// Local counter of launches (Analytics Events: "nothing transmitted", C1).
/// A plain integer file under Tauri's app-data dir, incremented once per
/// process start and never sent anywhere — no display surface consumes it
/// yet, so the return value is presently discarded by the caller. Failure to
/// read or write it (missing dir, permissions) is swallowed: a launch count
/// is diagnostic, not load-bearing, and must never block the window opening.
fn record_launch(app: &tauri::AppHandle) -> Option<u64> {
    let dir = app.path().app_data_dir().ok()?;
    std::fs::create_dir_all(&dir).ok()?;
    let path = dir.join("launch-count");
    let previous: u64 = std::fs::read_to_string(&path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);
    let next = previous + 1;
    std::fs::write(&path, next.to_string()).ok()?;
    Some(next)
}

/// Local-only lifecycle log — start/stop, this shell's version, and the API
/// version once known. Distinct from the hash-chained audit stores in
/// `docs/audit-log.md`: those record what Askwell told the user and why;
/// this records that a window process started and stopped, which is a
/// process-lifecycle fact, not a user-facing claim. Written to stdout so it
/// lands wherever the OS captures a launched app's output, same as every
/// other Askwell process.
fn log_event(app: &tauri::AppHandle, event: &str, api_version: Option<&str>) {
    let payload = serde_json::json!({
        "event": event,
        "shell_version": SHELL_VERSION,
        "api_version": api_version,
    });
    println!("{payload}");
    let _ = app; // reserved for a future structured-log plugin sink
}

// --- `M7-PACK-FE-143`: the supervision surface -------------------------------
//
// A second, small window over a second bundled asset (`supervision.html`,
// same trust level as `starting.html` — never retrieved content, so no C7
// boundary here either) rather than a route inside the real web app: the
// whole point of this ticket is that it must work "even when the API is
// down", and a page served by the API cannot be that page. It talks to the
// shell's own `supervisor::Handle` — already managed as app state since
// `M7-TAURI-DEPLOY-183` — through the three commands below, all scoped to
// the `supervision` window alone by `capabilities/supervision.json`, plus
// one more (`open_supervision_window`) granted to `main` so both required
// entry points — the native menu item above, and a button on the
// "assistant unavailable" state once the real app has loaded — can reach it.

/// Shared by the Tauri command and the native menu handler above: raised or
/// created, then focused. A second click while it is already open must not
/// spawn a second window pointed at the same state.
fn open_supervision_window_impl(app: &AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("supervision") {
        let _ = window.show();
        let _ = window.set_focus();
        return Ok(());
    }

    let origin = api_origin();
    let navigation_origin = origin.clone();
    let url = format!("supervision.html?api={}", urlencode(&origin));

    WebviewWindowBuilder::new(app, "supervision", WebviewUrl::App(url.into()))
        .title("Askwell — Supervision")
        .inner_size(560.0, 680.0)
        .min_inner_size(420.0, 480.0)
        .center()
        // Same C1/C7 boundary as the main window: this page never navigates
        // anywhere but its own bundled asset and the local API's origin.
        .on_navigation(move |url| is_allowed_navigation(url, &navigation_origin))
        .on_new_window(|_url, _features| NewWindowResponse::Deny)
        .build()
        .map(|_| ())
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn open_supervision_window(app: tauri::AppHandle) -> Result<(), String> {
    open_supervision_window_impl(&app)
}

#[derive(serde::Serialize)]
struct ComponentStatusDto {
    state: &'static str,
    reason: Option<String>,
    restarts: u64,
}

impl From<supervisor::ComponentStatus> for ComponentStatusDto {
    fn from(status: supervisor::ComponentStatus) -> Self {
        ComponentStatusDto { state: status.state, reason: status.reason, restarts: status.restarts }
    }
}

#[derive(serde::Serialize)]
struct SupervisionStatusDto {
    stack: ComponentStatusDto,
    inference: ComponentStatusDto,
}

/// Polled by `supervision.html` on an interval, not pushed — unlike the
/// starting page (guaranteed open for the loop's entire pre-handoff life),
/// this window usually does not exist at all, so there is nothing for the
/// loop to `eval` into most of the time.
#[tauri::command]
fn supervision_status(
    handle: tauri::State<'_, std::sync::Arc<supervisor::Handle>>,
) -> SupervisionStatusDto {
    let (stack, inference) = handle.status();
    SupervisionStatusDto { stack: stack.into(), inference: inference.into() }
}

/// `component` is `"stack"` or `"inference"`; the surface calls this twice
/// for "both", per this ticket's own scope line — the supervisor loop has no
/// notion of "both" and treating the two halves identically either way is
/// simpler than inventing a third target for one caller.
#[tauri::command]
fn supervision_control(
    component: String,
    action: String,
    handle: tauri::State<'_, std::sync::Arc<supervisor::Handle>>,
) -> Result<(), String> {
    let target = match component.as_str() {
        "stack" => supervisor::Target::Stack,
        "inference" => supervisor::Target::Inference,
        other => return Err(format!("Unknown component: {other}")),
    };
    let action = match action.as_str() {
        "start" => supervisor::ControlAction::Start,
        "stop" => supervisor::ControlAction::Stop,
        "restart" => supervisor::ControlAction::Restart,
        other => return Err(format!("Unknown action: {other}")),
    };
    handle.control(target, action);
    Ok(())
}

#[derive(serde::Serialize)]
struct LogLocation {
    path: String,
    note: String,
}

#[tauri::command]
fn supervision_log_location() -> LogLocation {
    let (dir, note) = supervisor::log_location();
    LogLocation { path: dir.to_string_lossy().into_owned(), note: note.to_string() }
}

// --- native dialogs and the scoped filesystem reads they unlock ------------
//
// `M7-TAURI-FE-182`. Five commands: three dialogs (`pick_folder` for root
// registration, `pick_file` for relocating a moved document, `pick_files` as
// the add-source screen's browse alternative) and two reads (`list_dir`,
// `read_head`) that let the frontend walk a chosen folder and detect what is
// inside it the same way it already does for a browser drop
// (`web/lib/add-source.ts`'s `flatten`/`HEAD_BYTES`).
//
// Nothing here copies a byte anywhere Askwell does not already put it: a
// dialog returns a path, `read_head` returns the first few kilobytes of one
// file for format detection, exactly the budget a browser-picked file already
// gets. Askwell still indexes in place — these commands exist so the frontend
// can *name* what is there, not so it can upload it.

/// The paths a dialog has actually handed back to this running session —
/// every `pick_folder`/`pick_file`/`pick_files` call adds one. `list_dir` and
/// `read_head` refuse anything that is not underneath one of these, which is
/// the fix for issue #580: without it, the IPC layer read whatever path
/// string the webview passed, with no check against a root the user actually
/// chose or the roots registry at all.
struct AllowedRoots(Mutex<HashSet<PathBuf>>);

fn allow_root(state: &AllowedRoots, path: &Path) {
    if let Ok(canonical) = path.canonicalize() {
        state.0.lock().unwrap().insert(canonical);
    }
}

/// True when `path` is, or is inside, a path a dialog has already returned.
/// Canonicalises both sides so a `..` segment or a symlink cannot be used to
/// step outside an allowed root while still textually starting with it.
fn is_within_allowed(state: &AllowedRoots, path: &Path) -> bool {
    let Ok(canonical) = path.canonicalize() else {
        return false;
    };
    state
        .0
        .lock()
        .unwrap()
        .iter()
        .any(|root| canonical.starts_with(root))
}

/// A refusal named by what actually went wrong, not a bare error — the
/// ticket's own edge case ("a directory the user cannot read — refused... with
/// the permission named, not with a missing-file message").
fn describe_io_error(path: &Path, error: &std::io::Error) -> String {
    match error.kind() {
        std::io::ErrorKind::PermissionDenied => {
            format!("Askwell does not have permission to read {}.", path.display())
        }
        std::io::ErrorKind::NotFound => format!("{} could not be found.", path.display()),
        _ => format!("Askwell could not read {}: {error}", path.display()),
    }
}

const OUTSIDE_CHOSEN_PATH: &str = "That path is outside every folder or file you chose.";

/// `to_string_lossy()` silently mangles a genuinely non-UTF-8 path (rare on
/// Linux/macOS, where a path is just bytes with no encoding guarantee) into
/// one that no longer names the file the user actually chose — issue #499's
/// finding. Refusing here, at the moment of picking, turns that into an
/// honest refusal instead of a `list_dir`/`read_head` failure against a
/// corrupted string later.
fn path_string(path: &Path) -> Result<String, String> {
    path.to_str().map(str::to_string).ok_or_else(|| {
        format!(
            "{} cannot be represented and cannot be chosen.",
            path.display()
        )
    })
}

#[tauri::command]
async fn pick_folder(state: tauri::State<'_, AllowedRoots>) -> Result<Option<String>, String> {
    let Some(handle) = rfd::AsyncFileDialog::new().pick_folder().await else {
        return Ok(None);
    };
    let path = handle.path().to_path_buf();
    let string = path_string(&path)?;
    allow_root(&state, &path);
    Ok(Some(string))
}

/// A path plus the size the shell already had to stat to grant it — sparing
/// the frontend a second round trip through `list_dir` just to learn how big
/// a file it was just handed is.
#[derive(serde::Serialize)]
struct PickedFile {
    path: String,
    size: u64,
}

fn picked_file(path: PathBuf, state: &AllowedRoots) -> Result<PickedFile, String> {
    let string = path_string(&path)?;
    if let Some(parent) = path.parent() {
        allow_root(state, parent);
    }
    allow_root(state, &path);
    let size = std::fs::metadata(&path).map(|meta| meta.len()).unwrap_or(0);
    Ok(PickedFile { path: string, size })
}

#[tauri::command]
async fn pick_file(state: tauri::State<'_, AllowedRoots>) -> Result<Option<PickedFile>, String> {
    let Some(handle) = rfd::AsyncFileDialog::new().pick_file().await else {
        return Ok(None);
    };
    Ok(Some(picked_file(handle.path().to_path_buf(), &state)?))
}

#[tauri::command]
async fn pick_files(state: tauri::State<'_, AllowedRoots>) -> Result<Vec<PickedFile>, String> {
    let Some(handles) = rfd::AsyncFileDialog::new().pick_files().await else {
        return Ok(Vec::new());
    };
    handles
        .into_iter()
        .map(|handle| picked_file(handle.path().to_path_buf(), &state))
        .collect()
}

#[derive(serde::Serialize)]
struct NativeDirEntry {
    name: String,
    path: String,
    is_dir: bool,
    size: u64,
}

/// The actual work, taking a plain reference rather than `tauri::State` —
/// `State` has no public constructor outside a running `App`, so a unit test
/// cannot build one to call the `#[tauri::command]` directly. Splitting the
/// scoping logic out this way is what makes `native_command_tests` runnable
/// at all.
fn list_dir_impl(path: &str, state: &AllowedRoots) -> Result<Vec<NativeDirEntry>, String> {
    let dir = PathBuf::from(path);
    if !is_within_allowed(state, &dir) {
        return Err(OUTSIDE_CHOSEN_PATH.to_string());
    }
    let read_dir = std::fs::read_dir(&dir).map_err(|error| describe_io_error(&dir, &error))?;
    let mut entries = Vec::new();
    for item in read_dir {
        let item = item.map_err(|error| describe_io_error(&dir, &error))?;
        // A non-UTF-8 name here (same rare case as #499, one level down)
        // cannot be named honestly over JSON — skipped from the listing
        // rather than corrupted into a name that resolves to nothing.
        let (Ok(name), Ok(path)) = (item.file_name().into_string(), path_string(&item.path()))
        else {
            continue;
        };
        let metadata = item.metadata().map_err(|error| describe_io_error(&item.path(), &error))?;
        entries.push(NativeDirEntry {
            name,
            path,
            is_dir: metadata.is_dir(),
            size: metadata.len(),
        });
    }
    Ok(entries)
}

#[tauri::command]
fn list_dir(path: String, state: tauri::State<'_, AllowedRoots>) -> Result<Vec<NativeDirEntry>, String> {
    list_dir_impl(&path, &state)
}

fn read_head_impl(path: &str, bytes: usize, state: &AllowedRoots) -> Result<Vec<u8>, String> {
    let file_path = PathBuf::from(path);
    if !is_within_allowed(state, &file_path) {
        return Err(OUTSIDE_CHOSEN_PATH.to_string());
    }
    let mut file = std::fs::File::open(&file_path).map_err(|error| describe_io_error(&file_path, &error))?;
    let mut buffer = vec![0u8; bytes];
    let read = file
        .read(&mut buffer)
        .map_err(|error| describe_io_error(&file_path, &error))?;
    buffer.truncate(read);
    Ok(buffer)
}

#[tauri::command]
fn read_head(path: String, bytes: usize, state: tauri::State<'_, AllowedRoots>) -> Result<Vec<u8>, String> {
    read_head_impl(&path, bytes, &state)
}

#[cfg(test)]
mod native_command_tests {
    use super::*;

    fn state() -> AllowedRoots {
        AllowedRoots(Mutex::new(HashSet::new()))
    }

    fn scratch_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "askwell-native-test-{name}-{}-{}",
            std::process::id(),
            name.len()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn path_string_accepts_an_ordinary_path() {
        assert_eq!(
            path_string(Path::new("/home/anna/clients/lease.pdf")).unwrap(),
            "/home/anna/clients/lease.pdf",
        );
    }

    #[test]
    #[cfg(unix)]
    fn path_string_refuses_genuinely_invalid_utf8() {
        use std::ffi::OsStr;
        use std::os::unix::ffi::OsStrExt;

        // 0x80 alone is never valid UTF-8 in any position.
        let invalid = OsStr::from_bytes(b"clients/le\x80se.pdf");
        assert!(path_string(Path::new(invalid)).is_err());
    }

    #[test]
    fn allows_a_path_under_a_granted_root() {
        let dir = scratch_dir("allowed");
        let file = dir.join("contract.pdf");
        std::fs::write(&file, b"hello").unwrap();

        let allowed = state();
        allow_root(&allowed, &dir);

        assert!(is_within_allowed(&allowed, &file));
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn refuses_a_path_outside_every_granted_root() {
        let granted = scratch_dir("granted");
        let other = scratch_dir("other");
        let secret = other.join("secret.txt");
        std::fs::write(&secret, b"hidden").unwrap();

        let allowed = state();
        allow_root(&allowed, &granted);

        assert!(!is_within_allowed(&allowed, &secret));
        std::fs::remove_dir_all(&granted).ok();
        std::fs::remove_dir_all(&other).ok();
    }

    #[test]
    fn read_head_refuses_a_path_never_granted() {
        let dir = scratch_dir("readhead-refuse");
        let file = dir.join("doc.txt");
        std::fs::write(&file, b"never granted").unwrap();

        let allowed = state();
        let result = read_head_impl(&file.to_string_lossy(), 4096, &allowed);

        assert!(result.is_err());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn read_head_returns_only_the_requested_bytes() {
        let dir = scratch_dir("readhead-allow");
        let file = dir.join("doc.txt");
        std::fs::write(&file, b"0123456789").unwrap();

        let allowed = state();
        allow_root(&allowed, &dir);
        let result = read_head_impl(&file.to_string_lossy(), 4, &allowed);

        assert_eq!(result.unwrap(), b"0123".to_vec());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn list_dir_refuses_a_path_never_granted() {
        let dir = scratch_dir("listdir-refuse");
        std::fs::write(dir.join("a.txt"), b"a").unwrap();

        let allowed = state();
        let result = list_dir_impl(&dir.to_string_lossy(), &allowed);

        assert!(result.is_err());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn list_dir_reports_names_and_kinds() {
        let dir = scratch_dir("listdir");
        std::fs::write(dir.join("a.txt"), b"a").unwrap();
        std::fs::create_dir(dir.join("sub")).unwrap();

        let allowed = state();
        allow_root(&allowed, &dir);
        let entries = list_dir_impl(&dir.to_string_lossy(), &allowed).unwrap();

        assert_eq!(entries.len(), 2);
        assert!(entries.iter().any(|e| e.name == "a.txt" && !e.is_dir));
        assert!(entries.iter().any(|e| e.name == "sub" && e.is_dir));
        std::fs::remove_dir_all(&dir).ok();
    }
}
