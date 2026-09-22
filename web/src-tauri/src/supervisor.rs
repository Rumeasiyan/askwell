//! `M7-TAURI-DEPLOY-183`: the shell supervises the container stack and the
//! native inference process while it is open, and stops both cleanly when it
//! quits.
//!
//! `M0-MODEL-BE-020` already gives the running application two causes of
//! "the assistant is unavailable" — the stack and the model — each reported
//! through `GET /health` once the API is reachable at all. This module adds
//! the third, which only exists because the shell now starts things rather
//! than a user having started them by hand first: the container runtime is
//! missing or not running, or the stack itself never comes up. Those two are
//! reported here, on the starting page, because nothing else can — there is
//! no API to ask yet. A model that fails to load, once the stack is up, is
//! still `M0-MODEL-BE-020`'s problem and is not touched here.
//!
//! Two known-fixed bugs from an earlier attempt at this ticket (filed as
//! issues #601, #602 before this rewrite) shaped the control flow below:
//! `RestartPolicy::reset` must only ever be called once a restart has
//! *proven* itself, not merely because a process is still alive at the next
//! poll tick, and a process that fails to even spawn must go through the same
//! backoff-and-report path as one that crashes after starting, rather than
//! being silently dropped. Issue #600 (adoption checked a Unix socket only,
//! so it never worked on Windows) is why adoption here is decided from
//! `state.json`'s heartbeat instead — the same file exists on every
//! platform.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use tauri::{AppHandle, Manager};

/// Mirrors `deploy/inference/askwell-inference`'s own `BACKOFF_SECONDS` —
/// five attempts, then give up. Kept identical on purpose: a user watching
/// both logs should not see two different retry rhythms for what looks like
/// the same kind of failure.
const BACKOFF_SECONDS: [u64; 5] = [1, 2, 5, 15, 30];

/// How often the loop checks on both halves. Short enough that "kill a
/// container, watch it come back" reads as prompt in a manual walkthrough;
/// long enough not to hammer `podman compose` or the health endpoint.
const POLL_INTERVAL: Duration = Duration::from_millis(1_500);

/// How long a single `/health` probe is allowed before counting as down.
const STACK_PROBE_TIMEOUT: Duration = Duration::from_secs(3);

/// Mirrors `api/src/askwell/inference/state.py`'s `STALE_AFTER_SECONDS`: the
/// supervisor rewrites `state.json` roughly every 10s while it runs, so a
/// heartbeat older than this means nothing is currently writing it, whether
/// or not the last state it recorded was `ready`.
const INFERENCE_STALE_AFTER_SECONDS: f64 = 35.0;

/// How long `stop()` waits for a SIGTERM'd process to exit on its own before
/// escalating to a hard kill — matches the Python supervisor's own shutdown
/// timeout (`deploy/inference/askwell-inference`'s `stop()`).
const GRACEFUL_STOP_TIMEOUT: Duration = Duration::from_secs(10);

// --- what gets reported on the starting page --------------------------------

/// The two shell-level causes this ticket adds, plus the transient states in
/// between. Serialised and pushed into `starting.html` via `WebviewWindow::eval`
/// rather than a Tauri command: the page is the shell's own bundled asset, not
/// retrieved content, so there is no C7 boundary to cross, and it avoids
/// widening `capabilities/default.json` for a read-only status line that
/// `M7-PACK-FE-143`'s repair surface will likely want to expose properly
/// anyway.
#[derive(Clone, PartialEq, serde::Serialize)]
#[serde(tag = "cause", rename_all = "snake_case")]
enum Cause {
    Starting,
    RuntimeMissing { detail: String },
    StackDown { detail: String },
    Ready,
}

fn report_on_window(app: &AppHandle, cause: &Cause) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let Ok(payload) = serde_json::to_string(cause) else {
        return;
    };
    let _ = window.eval(format!(
        "window.askwellReportCause && window.askwellReportCause({payload})"
    ));
}

// --- local, stdout-only supervision log --------------------------------------
//
// Distinct from the hash-chained audit stores (`docs/audit-log.md`) for the
// same reason `main.rs`'s own `log_event` is: this records that a process
// started, stopped or restarted, not a claim made to the user. "Start, stop,
// restart, backoff cap... logged with cause and timing" (this ticket's own
// Audit / Logging Requirement) is satisfied by this alone.

fn log_supervisor_event(component: &str, event: &str, reason: Option<&str>) {
    let payload = serde_json::json!({
        "event": event,
        "component": component,
        "reason": reason,
    });
    println!("{payload}");
}

// --- backoff -----------------------------------------------------------------

#[derive(Default)]
struct RestartPolicy {
    consecutive: usize,
    restarts: u64,
    last_reason: Option<String>,
}

impl RestartPolicy {
    /// Only ever called once the thing being restarted has *proven* itself —
    /// see this module's own docstring on issue #601. Calling it merely
    /// because a process is still running at the next poll is exactly the
    /// bug that made the give-up path unreachable in the earlier attempt.
    fn reset(&mut self) {
        self.consecutive = 0;
    }

    /// Records one failure and returns the delay before the next attempt, or
    /// `None` once five have happened in a row with no successful reset
    /// between them — at which point `last_reason` is what the caller should
    /// keep showing, per this ticket's "last reason retained" edge case.
    fn record_failure(&mut self, reason: impl Into<String>) -> Option<Duration> {
        self.last_reason = Some(reason.into());
        if self.consecutive >= BACKOFF_SECONDS.len() {
            return None;
        }
        let delay = BACKOFF_SECONDS[self.consecutive];
        self.consecutive += 1;
        self.restarts += 1;
        Some(Duration::from_secs(delay))
    }

    fn capped(&self) -> bool {
        self.consecutive >= BACKOFF_SECONDS.len()
    }
}

// --- where the stack and the inference script live ---------------------------

/// `deploy/linux/lib.sh`, `deploy/macos/lib.sh` and `deploy/windows/lib.ps1`
/// all place `compose.yaml`, `.env` and `askwell-inference` directly under
/// this one directory (`ASKWELL_INSTALL_PREFIX`, defaulted per platform) —
/// never inside the `.app`/`.exe`'s own bundle, which on macOS is a different
/// directory entirely. Resolving it the same way here, rather than deriving
/// it from `current_exe()`, is what keeps this in step with what the
/// installer actually wrote instead of guessing from the binary's own
/// location.
pub struct SupervisorConfig {
    pub install_root: PathBuf,
    pub run_dir: PathBuf,
    pub container_binary: String,
    pub api_origin: String,
}

fn home_dir() -> PathBuf {
    #[cfg(windows)]
    {
        std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap_or_default()
    }
    #[cfg(not(windows))]
    {
        std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default()
    }
}

fn platform_default_install_prefix() -> PathBuf {
    if cfg!(target_os = "macos") {
        home_dir().join("Library/Application Support/Askwell/app")
    } else if cfg!(windows) {
        let base = std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| home_dir().join("AppData/Local"));
        base.join("Askwell").join("app")
    } else {
        let base = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home_dir().join(".local/share"));
        base.join("askwell").join("app")
    }
}

/// The pure decision, split out from env/filesystem reads so it can be unit
/// tested without mutating process-global environment state.
fn resolve_install_root_from(
    override_prefix: Option<PathBuf>,
    default_prefix: PathBuf,
    repo_root: PathBuf,
) -> PathBuf {
    if let Some(dir) = override_prefix {
        return dir;
    }
    if default_prefix.join("compose.yaml").is_file() {
        return default_prefix;
    }
    // `cargo tauri dev`/`cargo test` run from a `target/` directory with no
    // installed prefix at all — fall back to the repo `build.rs` baked in,
    // exactly as `ASKWELL_SHELL_VERSION` already does for the version.
    if repo_root.join("compose.yaml").is_file() {
        return repo_root;
    }
    default_prefix
}

pub fn resolve_install_root() -> PathBuf {
    resolve_install_root_from(
        std::env::var_os("ASKWELL_INSTALL_PREFIX").map(PathBuf::from),
        platform_default_install_prefix(),
        PathBuf::from(env!("ASKWELL_REPO_ROOT")),
    )
}

/// A minimal `KEY=VALUE` reader for the installer-written `.env` — `podman
/// compose` loads this file itself from `--project-directory`, but
/// `Command::spawn` for the native inference process does not, and the
/// generation/embedding/reranking model paths (`ASKWELL_INFERENCE_MODEL_PATH`
/// and friends, `.env.example`) live only there. Deliberately not a crate:
/// the format in use here is a handful of unquoted `NAME=value` lines, the
/// same shape `deploy/*/lib.*`'s own `generate_env_passwords` already writes.
fn read_env_file(path: &Path) -> Vec<(String, String)> {
    let Ok(contents) = fs::read_to_string(path) else {
        return Vec::new();
    };
    contents
        .lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                return None;
            }
            let (key, value) = line.split_once('=')?;
            let key = key.trim();
            let mut value = value.trim();
            if (value.starts_with('"') && value.ends_with('"') && value.len() >= 2)
                || (value.starts_with('\'') && value.ends_with('\'') && value.len() >= 2)
            {
                value = &value[1..value.len() - 1];
            }
            if key.is_empty() {
                None
            } else {
                Some((key.to_string(), value.to_string()))
            }
        })
        .collect()
}

// --- the container stack ------------------------------------------------------

fn compose(config: &SupervisorConfig, args: &[&str]) -> std::io::Result<std::process::Output> {
    Command::new(&config.container_binary)
        .arg("compose")
        .arg("--project-directory")
        .arg(&config.install_root)
        .arg("-f")
        .arg(config.install_root.join("compose.yaml"))
        .args(args)
        .env("ASKWELL_RUN_DIR", &config.run_dir)
        .current_dir(&config.install_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
}

/// Phrases `podman compose` actually prints when the daemon itself is the
/// problem, distinguishing "Podman is not running" from "the stack failed to
/// come up" — the ticket's own edge case names these as different causes with
/// different fixes ("Askwell cannot start it" vs. a stack-level failure).
fn looks_like_runtime_down(stderr: &str) -> bool {
    let lowered = stderr.to_lowercase();
    lowered.contains("cannot connect")
        || lowered.contains("connection refused")
        || lowered.contains("is podman running")
        || lowered.contains("no such host")
        || (lowered.contains("machine") && lowered.contains("not running"))
}

fn stack_up(config: &SupervisorConfig) -> Result<(), Cause> {
    if !config.install_root.join("compose.yaml").is_file() {
        return Err(Cause::StackDown {
            detail: format!(
                "No compose.yaml at {}. Reinstall Askwell.",
                config.install_root.display()
            ),
        });
    }

    match compose(config, &["up", "-d"]) {
        Ok(output) if output.status.success() => Ok(()),
        Ok(output) => {
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            let detail = if stderr.is_empty() {
                format!(
                    "`{} compose up -d` exited with {}.",
                    config.container_binary, output.status
                )
            } else {
                stderr
            };
            if looks_like_runtime_down(&detail) {
                Err(Cause::RuntimeMissing {
                    detail: format!(
                        "{} is installed but not running. Start it, then reopen Askwell. ({detail})",
                        config.container_binary
                    ),
                })
            } else {
                Err(Cause::StackDown { detail })
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Err(Cause::RuntimeMissing {
            detail: format!(
                "{} is not installed. Askwell needs it to run its container stack — install it, then reopen Askwell.",
                config.container_binary
            ),
        }),
        Err(error) => Err(Cause::RuntimeMissing {
            detail: format!("Could not run {}: {error}", config.container_binary),
        }),
    }
}

fn compose_down(config: &SupervisorConfig) {
    match compose(config, &["down"]) {
        Ok(output) if !output.status.success() => {
            log_supervisor_event(
                "stack",
                "supervisor_stack_down_failed",
                Some(String::from_utf8_lossy(&output.stderr).trim()),
            );
        }
        Err(error) => {
            log_supervisor_event("stack", "supervisor_stack_down_failed", Some(&error.to_string()));
        }
        _ => {}
    }
}

/// Reachability, not health — matching `health.py`'s own stated distinction.
/// The stack side of this module only needs "the api container is answering
/// at all"; per-component detail (database, worker, inference…) is
/// `M0-MODEL-BE-020`'s job, rendered once the shell has handed off to the
/// real application.
fn stack_reachable(api_origin: &str) -> bool {
    let agent = ureq::Agent::config_builder()
        .timeout_global(Some(STACK_PROBE_TIMEOUT))
        .build()
        .new_agent();
    agent.get(format!("{api_origin}/health")).call().is_ok()
}

// --- the native inference process ---------------------------------------------

fn inference_state_json(run_dir: &Path) -> Option<serde_json::Value> {
    let text = fs::read_to_string(run_dir.join("state.json")).ok()?;
    serde_json::from_str(&text).ok()
}

/// Whether *something* is currently writing `state.json` — the supervisor
/// heartbeats roughly every 10s while it runs (`HEARTBEAT_SECONDS`,
/// `deploy/inference/askwell-inference`), so a fresh timestamp means a live
/// process already owns this role, regardless of what state it last
/// reported. Reading the same file every platform's supervisor already
/// writes is what makes this check work identically on Linux, macOS and
/// Windows — the earlier attempt's version of this (issue #600) instead
/// connected to a Unix socket, which does not exist on Windows at all.
fn inference_heartbeat_fresh(run_dir: &Path) -> bool {
    let Some(value) = inference_state_json(run_dir) else {
        return false;
    };
    let Some(updated_at) = value.get("updated_at").and_then(|v| v.as_f64()) else {
        return false;
    };
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);
    now - updated_at <= INFERENCE_STALE_AFTER_SECONDS
}

/// True only once generation has actually answered, matching
/// `ProcessState.READY` in `api/src/askwell/inference/state.py`. This is the
/// readiness signal `RestartPolicy::reset` waits for — not "the OS process is
/// still alive", which is what made the give-up path unreachable before
/// (issue #601).
fn inference_confirmed_ready(run_dir: &Path) -> bool {
    let Some(value) = inference_state_json(run_dir) else {
        return false;
    };
    if value.get("state").and_then(|v| v.as_str()) != Some("ready") {
        return false;
    }
    inference_heartbeat_fresh(run_dir)
}

fn inference_last_reason(run_dir: &Path) -> Option<String> {
    inference_state_json(run_dir)?
        .get("reason")
        .and_then(|v| v.as_str())
        .map(str::to_string)
}

fn python_candidates() -> &'static [&'static str] {
    // `deploy/windows/install.ps1` tries `python` then falls back to `py`;
    // `deploy/macos/install.sh` and `deploy/linux/install.sh` both use
    // `python3` — matched here rather than invented, so a machine that can
    // run the installer's own probe step can run this too.
    if cfg!(windows) {
        &["python", "py"]
    } else {
        &["python3"]
    }
}

fn spawn_inference(config: &SupervisorConfig) -> Result<Child, String> {
    let script = config.install_root.join("askwell-inference");
    if !script.is_file() {
        return Err(format!(
            "{} is missing. Reinstall Askwell, or an antivirus tool may have removed it.",
            script.display()
        ));
    }

    let env_vars = read_env_file(&config.install_root.join(".env"));
    let mut last_error: Option<String> = None;

    for interpreter in python_candidates() {
        let mut command = Command::new(interpreter);
        command
            .arg(&script)
            .envs(env_vars.iter().map(|(k, v)| (k.as_str(), v.as_str())))
            .env("ASKWELL_INFERENCE_SOCKET", config.run_dir.join("inference.sock"))
            .current_dir(&config.install_root)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        match command.spawn() {
            Ok(child) => return Ok(child),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                last_error = Some(format!("{interpreter} is not on PATH"));
                continue;
            }
            Err(error) => {
                return Err(format!("Could not start {}: {error}", script.display()));
            }
        }
    }

    Err(last_error.unwrap_or_else(|| "No Python interpreter was found on PATH.".to_string()))
}

#[cfg(unix)]
fn terminate_child(child: &mut Child) {
    // SIGTERM first — matching the Python supervisor's own shutdown, which
    // gives `llama-server` a chance to exit on its own (`stop()`,
    // `deploy/inference/askwell-inference`) rather than being hard-killed
    // and potentially leaving its own subprocess behind.
    let pid = child.id() as libc::pid_t;
    unsafe {
        libc::kill(pid, libc::SIGTERM);
    }
    let deadline = Instant::now() + GRACEFUL_STOP_TIMEOUT;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(200)),
            _ => break,
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg(not(unix))]
fn terminate_child(child: &mut Child) {
    // Windows has no SIGTERM equivalent reachable from `std`, and the Python
    // supervisor's own graceful-shutdown signal handler already silently
    // fails to register there (`contextlib.suppress(NotImplementedError)`,
    // `deploy/inference/askwell-inference`) — a hard kill here is not a
    // regression against what already happens on that platform.
    let _ = child.kill();
    let _ = child.wait();
}

// --- the supervision loop ------------------------------------------------------

pub struct Handle {
    stopping: Arc<AtomicBool>,
    stopped_once: AtomicBool,
    join: Mutex<Option<thread::JoinHandle<()>>>,
}

impl Handle {
    /// Idempotent — `RunEvent::ExitRequested` can fire more than once (one
    /// per window), and this must still only try to stop everything once.
    pub fn stop_and_wait(&self) {
        if self.stopped_once.swap(true, Ordering::SeqCst) {
            return;
        }
        self.stopping.store(true, Ordering::SeqCst);
        if let Some(handle) = self.join.lock().unwrap().take() {
            let _ = handle.join();
        }
    }
}

pub fn start(app: AppHandle, config: SupervisorConfig) -> Arc<Handle> {
    let stopping = Arc::new(AtomicBool::new(false));
    let loop_stopping = stopping.clone();
    let join = thread::spawn(move || run(app, config, loop_stopping));
    Arc::new(Handle {
        stopping,
        stopped_once: AtomicBool::new(false),
        join: Mutex::new(Some(join)),
    })
}

fn wait_or_stop(stopping: &AtomicBool, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if stopping.load(Ordering::SeqCst) {
            return true;
        }
        thread::sleep(Duration::from_millis(150));
    }
    stopping.load(Ordering::SeqCst)
}

fn run(app: AppHandle, config: SupervisorConfig, stopping: Arc<AtomicBool>) {
    report_on_window(&app, &Cause::Starting);

    // Ordered start: the stack first, then the native process — deterministic
    // rather than a race, per this ticket's own scope line.
    let mut stack_policy = RestartPolicy::default();
    let mut stack_up_confirmed = false;
    let mut last_reported: Option<Cause> = None;
    log_supervisor_event("stack", "supervisor_stack_start", None);
    attempt_stack_up(&app, &config, &mut stack_policy, &mut last_reported);

    let mut inference: Option<Child> = None;
    let mut inference_policy = RestartPolicy::default();
    let mut inference_confirmed = false;
    let mut inference_capped = false;
    let mut next_inference_attempt = Instant::now();
    log_supervisor_event("inference", "supervisor_inference_start", None);
    if let Some(delay) = bring_up_inference(&config, &mut inference, &mut inference_policy) {
        next_inference_attempt = Instant::now() + delay;
    }

    let mut next_stack_attempt = Instant::now();

    loop {
        if stopping.load(Ordering::SeqCst) {
            break;
        }

        // --- stack ---
        if stack_reachable(&config.api_origin) {
            if !stack_up_confirmed {
                stack_policy.reset();
                stack_up_confirmed = true;
                log_supervisor_event("stack", "supervisor_stack_ready", None);
                set_reported(&app, &mut last_reported, Cause::Ready);
            }
        } else {
            stack_up_confirmed = false;
            if !stack_policy.capped() && Instant::now() >= next_stack_attempt {
                if let Some(delay) = attempt_stack_up(&app, &config, &mut stack_policy, &mut last_reported) {
                    next_stack_attempt = Instant::now() + delay;
                }
            }
        }

        // --- inference ---
        match inference.as_mut() {
            Some(child) => match child.try_wait() {
                Ok(None) => {
                    if !inference_confirmed && inference_confirmed_ready(&config.run_dir) {
                        inference_policy.reset();
                        inference_confirmed = true;
                        inference_capped = false;
                        log_supervisor_event("inference", "supervisor_inference_ready", None);
                    }
                }
                Ok(Some(status)) => {
                    let reason = inference_last_reason(&config.run_dir)
                        .unwrap_or_else(|| format!("askwell-inference exited with {status}"));
                    inference = None;
                    inference_confirmed = false;
                    match inference_policy.record_failure(reason.clone()) {
                        Some(delay) => {
                            log_supervisor_event("inference", "supervisor_inference_restart", Some(&reason));
                            next_inference_attempt = Instant::now() + delay;
                        }
                        None => {
                            inference_capped = true;
                            log_supervisor_event("inference", "supervisor_inference_failed", Some(&reason));
                        }
                    }
                }
                Err(error) => {
                    log_supervisor_event(
                        "inference",
                        "supervisor_inference_poll_error",
                        Some(&error.to_string()),
                    );
                }
            },
            None => {
                if !inference_capped && Instant::now() >= next_inference_attempt {
                    if let Some(delay) = bring_up_inference(&config, &mut inference, &mut inference_policy) {
                        next_inference_attempt = Instant::now() + delay;
                    }
                }
            }
        }

        if wait_or_stop(&stopping, POLL_INTERVAL) {
            break;
        }
    }

    log_supervisor_event("shell", "supervisor_stop", None);
    if let Some(mut child) = inference.take() {
        terminate_child(&mut child);
    }
    compose_down(&config);
}

fn attempt_stack_up(
    app: &AppHandle,
    config: &SupervisorConfig,
    policy: &mut RestartPolicy,
    last_reported: &mut Option<Cause>,
) -> Option<Duration> {
    match stack_up(config) {
        Ok(()) => None,
        Err(cause) => {
            let detail = match &cause {
                Cause::RuntimeMissing { detail } | Cause::StackDown { detail } => detail.clone(),
                _ => String::new(),
            };
            match policy.record_failure(detail) {
                Some(delay) => {
                    log_supervisor_event("stack", "supervisor_stack_restart", policy.last_reason.as_deref());
                    Some(delay)
                }
                None => {
                    log_supervisor_event("stack", "supervisor_stack_failed", policy.last_reason.as_deref());
                    set_reported(app, last_reported, cause);
                    None
                }
            }
        }
    }
}

/// Spawns the native inference process, unless a live one is already
/// answering (adoption — this ticket's "the shell is killed rather than
/// quit" and "the stack is already running... the shell attaches" edge
/// cases, the inference half of it). A spawn failure goes through the same
/// `RestartPolicy` a crash does, so it retries with backoff and eventually
/// reaches the capped, reason-retained state instead of being silently
/// dropped — the fix for issue #602.
fn bring_up_inference(
    config: &SupervisorConfig,
    slot: &mut Option<Child>,
    policy: &mut RestartPolicy,
) -> Option<Duration> {
    if inference_heartbeat_fresh(&config.run_dir) {
        log_supervisor_event("inference", "supervisor_inference_adopted", None);
        return None;
    }
    match spawn_inference(config) {
        Ok(child) => {
            *slot = Some(child);
            None
        }
        Err(reason) => match policy.record_failure(reason.clone()) {
            Some(delay) => {
                log_supervisor_event("inference", "supervisor_inference_spawn_retry", Some(&reason));
                Some(delay)
            }
            None => {
                log_supervisor_event("inference", "supervisor_inference_failed", Some(&reason));
                None
            }
        },
    }
}

fn set_reported(app: &AppHandle, last_reported: &mut Option<Cause>, cause: Cause) {
    if last_reported.as_ref() == Some(&cause) {
        return;
    }
    report_on_window(app, &cause);
    *last_reported = Some(cause);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn restart_policy_walks_the_backoff_then_caps() {
        let mut policy = RestartPolicy::default();
        let expected = [1, 2, 5, 15, 30];
        for seconds in expected {
            let delay = policy.record_failure("boom").expect("not capped yet");
            assert_eq!(delay, Duration::from_secs(seconds));
        }
        assert!(policy.capped());
        assert!(policy.record_failure("boom again").is_none());
        assert_eq!(policy.last_reason.as_deref(), Some("boom again"));
    }

    #[test]
    fn restart_policy_reset_reopens_the_backoff() {
        let mut policy = RestartPolicy::default();
        policy.record_failure("a");
        policy.record_failure("b");
        policy.reset();
        let delay = policy.record_failure("c").expect("reset should reopen the walk");
        assert_eq!(delay, Duration::from_secs(1));
    }

    #[test]
    fn restart_policy_reset_does_not_erase_the_last_reason() {
        // The edge case is explicit: "the state becomes failed with the last
        // reason retained". A `reset()` after a successful restart must not
        // be able to blank out a reason that has not been superseded by a
        // newer failure.
        let mut policy = RestartPolicy::default();
        policy.record_failure("disk full");
        policy.reset();
        assert_eq!(policy.last_reason.as_deref(), Some("disk full"));
    }

    #[test]
    fn resolve_install_root_prefers_explicit_override() {
        let resolved = resolve_install_root_from(
            Some(PathBuf::from("/opt/askwell")),
            PathBuf::from("/should/not/be/used"),
            PathBuf::from("/also/not/used"),
        );
        assert_eq!(resolved, PathBuf::from("/opt/askwell"));
    }

    #[test]
    fn resolve_install_root_falls_back_to_repo_root_when_nothing_is_installed() {
        let dir = std::env::temp_dir().join(format!(
            "askwell-supervisor-test-repo-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("compose.yaml"), "name: askwell").unwrap();

        let resolved = resolve_install_root_from(
            None,
            PathBuf::from("/definitely/not/installed/anywhere"),
            dir.clone(),
        );
        assert_eq!(resolved, dir);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn looks_like_runtime_down_detects_common_podman_phrasing() {
        assert!(looks_like_runtime_down(
            "Error: unable to connect to Podman socket: cannot connect"
        ));
        assert!(looks_like_runtime_down(
            "Error: podman machine \"podman-machine-default\" is not running"
        ));
        assert!(!looks_like_runtime_down(
            "Error: image build failed: Dockerfile not found"
        ));
    }

    #[test]
    fn read_env_file_parses_pairs_and_skips_comments() {
        let dir = std::env::temp_dir().join(format!("askwell-supervisor-test-env-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join(".env");
        fs::write(
            &path,
            "# a comment\nASKWELL_PORT=8000\n\nASKWELL_INFERENCE_MODEL_PATH=\"/models/x.gguf\"\n",
        )
        .unwrap();

        let pairs: HashMap<_, _> = read_env_file(&path).into_iter().collect();
        assert_eq!(pairs.get("ASKWELL_PORT").map(String::as_str), Some("8000"));
        assert_eq!(
            pairs.get("ASKWELL_INFERENCE_MODEL_PATH").map(String::as_str),
            Some("/models/x.gguf")
        );
        assert_eq!(pairs.len(), 2);
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn inference_heartbeat_fresh_is_false_for_a_stale_file() {
        let dir = std::env::temp_dir().join(format!(
            "askwell-supervisor-test-stale-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let old = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64()
            - 3600.0;
        fs::write(
            dir.join("state.json"),
            serde_json::json!({"state": "ready", "updated_at": old}).to_string(),
        )
        .unwrap();

        assert!(!inference_heartbeat_fresh(&dir));
        assert!(!inference_confirmed_ready(&dir));
        fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn inference_confirmed_ready_requires_both_state_and_freshness() {
        let dir = std::env::temp_dir().join(format!(
            "askwell-supervisor-test-ready-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();

        fs::write(
            dir.join("state.json"),
            serde_json::json!({"state": "starting", "updated_at": now}).to_string(),
        )
        .unwrap();
        assert!(inference_heartbeat_fresh(&dir));
        assert!(!inference_confirmed_ready(&dir), "starting is not ready");

        fs::write(
            dir.join("state.json"),
            serde_json::json!({"state": "ready", "updated_at": now}).to_string(),
        )
        .unwrap();
        assert!(inference_confirmed_ready(&dir));
        fs::remove_dir_all(&dir).ok();
    }
}
