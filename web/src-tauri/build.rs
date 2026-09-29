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
    // `generate_handler!` in `main.rs` identical.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&[
                "pick_folder",
                "pick_files",
                "pick_file",
                "list_dir",
                "read_head",
                "open_supervision_window",
                "supervision_status",
                "supervision_control",
                "supervision_log_location",
            ]),
        ),
    )
    .expect("failed to run tauri-build");
}
