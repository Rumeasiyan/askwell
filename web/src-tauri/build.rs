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

    // `M7-TAURI-FE-182`'s five commands (native dialogs plus the two scoped
    // filesystem reads they unlock) need to be named here so tauri-build can
    // autogenerate the `allow-*`/`deny-*` permissions `capabilities/default.json`
    // grants — a command not listed here has no permission to grant at all,
    // regardless of what the capabilities file says.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&[
                "pick_folder",
                "pick_files",
                "pick_file",
                "list_dir",
                "read_head",
            ]),
        ),
    )
    .expect("failed to run tauri-build");
}
