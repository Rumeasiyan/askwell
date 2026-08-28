from pathlib import Path

from eval.prompt_versions import default_prompts_dir, read_prompt_versions


def test_reads_real_prompt_files() -> None:
    versions = read_prompt_versions(default_prompts_dir())
    assert versions["abstention"] == "v1"
    assert versions["answer_composition"] == "v1"


def test_ignores_files_with_no_version_suffix(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("not a prompt file")
    (tmp_path / "abstention.v2.md").write_text("...")
    versions = read_prompt_versions(tmp_path)
    assert versions == {"abstention": "v2"}
