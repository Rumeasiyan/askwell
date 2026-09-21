// Prevents an extra console window from opening on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::webview::NewWindowResponse;
use tauri::{Manager, Url, WebviewUrl, WebviewWindowBuilder};

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

            Ok(())
        })
        .build(tauri::generate_context!());

    match builder {
        Ok(app) => {
            app.run(|app_handle, event| {
                if let tauri::RunEvent::ExitRequested { .. } = event {
                    log_event(app_handle, "shell_stop", None);
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
