use std::collections::BTreeSet;
use std::fs;
use std::path::Path;

fn main() {
    // AGENTS.md §7: `VERSION` at the repo root is the one canonical version.
    // Reading it at compile time (rather than hand-copying it into
    // `Cargo.toml` or `tauri.conf.json`) is what keeps the shell from
    // becoming a second place that number has to be kept in sync by hand.
    let version_path = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../VERSION");
    let version = fs::read_to_string(&version_path)
        .unwrap_or_else(|error| panic!("could not read {}: {error}", version_path.display()))
        .trim()
        .to_string();
    println!("cargo:rustc-env=ASKWELL_SHELL_VERSION={version}");
    println!("cargo:rerun-if-changed={}", version_path.display());

    // `supervisor.rs` needs `compose.yaml` and `deploy/inference/askwell-inference`.
    // An installed build finds them under the platform install prefix
    // (`ASKWELL_INSTALL_PREFIX`, see `deploy/*/lib.*`); baking the repo root
    // in here too is what lets `cargo tauri dev` find them without that
    // installer having run — the same pattern `ASKWELL_SHELL_VERSION` already
    // uses for the same reason (a build-time fact the binary cannot discover
    // any other way once running from a `target/` directory).
    let repo_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let repo_root = fs::canonicalize(&repo_root)
        .unwrap_or_else(|error| panic!("could not resolve {}: {error}", repo_root.display()));
    println!("cargo:rustc-env=ASKWELL_REPO_ROOT={}", repo_root.display());

    // Every command `main.rs` registers has to be named here so tauri-build
    // can autogenerate the `allow-*`/`deny-*` permissions the capabilities
    // grant — a command not listed here has no permission to grant at all,
    // regardless of what the capabilities file says. `M7-TAURI-FE-182`'s five
    // (native dialogs plus the two scoped filesystem reads they unlock), then
    // `M7-PACK-FE-143`'s four supervision commands, which were registered and
    // granted but never listed here: the shell had never been compiled in CI
    // until the first release build (v0.9.0), and all three platforms failed
    // on `allow-open-supervision-window not found`. Keep this list and
    // `generate_handler!` in `main.rs` identical — `check_commands_match_main`
    // below fails the build if they differ (M10-TEST-DEPLOY-221).
    const COMMANDS: &[&str] = &[
        "pick_folder",
        "pick_files",
        "pick_file",
        "list_dir",
        "read_head",
        "open_supervision_window",
        "supervision_status",
        "supervision_control",
        "supervision_log_location",
    ];
    check_commands_match_main(COMMANDS);

    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(COMMANDS)),
    )
    .expect("failed to run tauri-build");
}

/// Fails the build unless `commands` names exactly the handlers in
/// `generate_handler!` in `src/main.rs`.
///
/// tauri-build catches only one direction of drift, and only by accident: a
/// command missing here fails if a capability happens to grant it, and
/// otherwise compiles into a command no permission can ever allow. A name here
/// that `main.rs` no longer registers fails nowhere. Running before
/// `try_build` means the message names the actual mismatch rather than a
/// missing `allow-*` permission, which is what v0.9.0's release build said
/// (issue #821).
fn check_commands_match_main(commands: &[&str]) {
    let main_path = Path::new(env!("CARGO_MANIFEST_DIR")).join("src/main.rs");
    println!("cargo:rerun-if-changed={}", main_path.display());
    let main_source = fs::read_to_string(&main_path)
        .unwrap_or_else(|error| panic!("could not read {}: {error}", main_path.display()));

    const MARKER: &str = "generate_handler![";
    let start = main_source
        .find(MARKER)
        .unwrap_or_else(|| panic!("no `{MARKER}` in {}", main_path.display()))
        + MARKER.len();
    let end = start
        + main_source[start..]
            .find(']')
            .unwrap_or_else(|| panic!("unclosed `{MARKER}` in {}", main_path.display()));
    let registered: BTreeSet<&str> = main_source[start..end]
        .split(',')
        .map(str::trim)
        .filter(|name| !name.is_empty())
        .collect();
    let declared: BTreeSet<&str> = commands.iter().copied().collect();

    let unlisted: Vec<_> = registered.difference(&declared).collect();
    let unregistered: Vec<_> = declared.difference(&registered).collect();
    if !unlisted.is_empty() || !unregistered.is_empty() {
        panic!(
            "build.rs's command list and `generate_handler!` in src/main.rs differ.\n  \
             registered in main.rs but not listed in build.rs: {unlisted:?}\n  \
             listed in build.rs but not registered in main.rs: {unregistered:?}\n\
             Keep the two identical: a command missing from build.rs has no permission a \
             capability can grant."
        );
    }
}
