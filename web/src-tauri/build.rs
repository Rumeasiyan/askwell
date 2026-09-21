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

    tauri_build::build();
}
