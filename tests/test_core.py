"""Build-side identity, strict provenance and selection behavior."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from setuptools_git_metadata.core import ProjectMetadata
from setuptools_git_metadata.schema import _loads, _validate
from tests.conftest import inventory


def test_selected_source_changes(project):
    metadata = ProjectMetadata(project, "src/example")
    before = inventory(project)
    original = metadata.payload()
    assert original["PACKAGE_VERSION"] == original["BUILD_VERSION"] == "1.2.3"
    assert len(original["BUILD_GIT_HASH"]) == 40
    assert original["BUILD_GIT_DIRTY"] is False
    for name in ("excluded.txt", "ignored.txt"):
        (project / name).write_text("changed", encoding="utf-8")
        assert metadata.payload()["BUILD_GIT_DIRTY"] is False
    data = project / "src/example/data.txt"
    data.unlink()
    assert metadata.payload()["BUILD_GIT_DIRTY"] is True
    data.write_text("package data", encoding="utf-8")
    for name in ("new.py", "with space.py", "café.py"):
        path = project / "src/example" / name
        path.write_text("# selected untracked", encoding="utf-8")
        assert metadata.payload()["BUILD_GIT_DIRTY"] is True
        path.unlink()
    template = project / "src/example/_version.py"
    template.write_bytes(template.read_bytes() + b'\nCUSTOM = "changed"\n')
    changed = metadata.payload()
    assert changed["BUILD_GIT_DIRTY"] is True
    assert changed["SELECTED_SOURCE_DIGEST"] != original["SELECTED_SOURCE_DIGEST"]
    assert "ignored.txt" in before  # Ignored source is actually inventoried.


def test_detached_and_shallow(project, tmp_path):
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth=1", "--no-local", project.as_uri(), str(clone)],
        check=True,
        capture_output=True,
    )
    metadata = ProjectMetadata(clone, "src/example")
    assert metadata.payload()["BUILD_GIT_DIRTY"] is False
    subprocess.run(["git", "checkout", "--detach"], cwd=clone, check=True, capture_output=True)
    assert metadata.payload()["BUILD_GIT_BRANCH"] is None


def test_selector_failure_not_missing_git(project, monkeypatch):
    metadata = ProjectMetadata(project, "src/example")

    def failed():
        raise subprocess.CalledProcessError(1, ["selection"])

    monkeypatch.setattr(metadata, "selected_dirty", failed)
    with pytest.raises(subprocess.CalledProcessError):
        metadata.payload()


def test_hardlink_write_does_not_change_original(tmp_path):
    original = tmp_path / "original.json"
    original.write_text("original", encoding="utf-8")
    staged = tmp_path / "staged.json"
    os.link(original, staged)
    ProjectMetadata.atomic_write(staged, "replacement")
    assert original.read_text(encoding="utf-8") == "original"
    assert staged.read_text(encoding="utf-8") == "replacement"


@pytest.mark.parametrize("invalid", ["-1", "", "false", "1.0", "１２"])
def test_invalid_clock(invalid, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", invalid)
    with pytest.raises(ValueError, match="SOURCE_DATE_EPOCH"):
        ProjectMetadata.event_time()


def test_unknown_mode_before_output(project, tmp_path):
    config = project / "pyproject.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "[tool.setuptools-git-metadata]",
            '[tool.setuptools-git-metadata]\nversion-mode="branch"',
        ),
        encoding="utf-8",
    )
    target = tmp_path / "not-created"
    with pytest.raises(NotImplementedError):
        ProjectMetadata(project, "src/example").render(target)
    assert not target.exists()


def test_baked_priority_and_epoch_zero(project, tmp_path, monkeypatch):
    metadata = ProjectMetadata(project, "src/example")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    metadata.render(tmp_path / "first")
    baked = _loads((tmp_path / "first/_provenance.json").read_text(encoding="utf-8"))
    assert baked["BUILD_GIT_DIRTY"] is False and baked["SOURCE_TIMESTAMP"] == 0
    (project / "src/example/_provenance.json").write_text(json.dumps(baked), encoding="utf-8")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "100")
    metadata.render(tmp_path / "wheel", wheel=True)
    rebuilt = _loads((tmp_path / "wheel/_provenance.json").read_text(encoding="utf-8"))
    assert rebuilt["SOURCE_TIMESTAMP"] == rebuilt["SDIST_BUILD_TIMESTAMP"] == 0
    assert rebuilt["BUILD_TIMESTAMP"] == rebuilt["WHEEL_BUILD_TIMESTAMP"] == 100
    assert rebuilt["BUILD_GIT_HASH"] == baked["BUILD_GIT_HASH"]
    with pytest.raises(ValueError, match="baked version"):
        metadata.validate_baked(baked, "2.0.0")


@pytest.mark.parametrize(
    "field",
    [
        "schema_version",
        "BUILD_TIMESTAMP",
        "SOURCE_TIMESTAMP",
        "SDIST_BUILD_TIMESTAMP",
        "WHEEL_BUILD_TIMESTAMP",
    ],
)
def test_bool_is_not_timestamp_or_schema(project, tmp_path, field):
    ProjectMetadata(project, "src/example").render(tmp_path / "payload")
    data = _loads((tmp_path / "payload/_provenance.json").read_text(encoding="utf-8"))
    data[field] = True
    with pytest.raises(ValueError):
        _validate(data)


def test_strict_json():
    for text in ('{"schema_version":1,"schema_version":1}', '{"x":NaN}', "{bad", "{}"):
        with pytest.raises(ValueError):
            _loads(text)


def test_package_escape(tmp_path):
    with pytest.raises(ValueError, match="inside source"):
        ProjectMetadata(tmp_path, "../outside")


def test_nested_project_uses_relative_git_paths(project):
    import shutil

    nested = project / "packages" / "example"
    nested.mkdir(parents=True)
    for path in list(project.iterdir()):
        if path.name not in (".git", "packages"):
            shutil.move(str(path), nested / path.name)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "nested project"], cwd=project, check=True, capture_output=True
    )
    metadata = ProjectMetadata(nested, "src/example")
    assert metadata.payload()["BUILD_GIT_DIRTY"] is False
    (project / "outside.txt").write_text("not a distribution input", encoding="utf-8")
    assert metadata.payload()["BUILD_GIT_DIRTY"] is False
    (nested / "README.md").write_text("selected", encoding="utf-8")
    assert metadata.payload()["BUILD_GIT_DIRTY"] is True


@pytest.mark.skipif(os.name == "nt", reason="Windows prohibits newline characters in filenames")
def test_newline_filename_has_explicit_error(project):
    (project / "src/example/new\nline.py").write_text(
        "# cannot represent in SOURCES.txt", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="newline filenames"):
        ProjectMetadata(project, "src/example").payload()


def test_absolute_package_directory_is_staged_as_relative(project):
    metadata = ProjectMetadata(project, project / "src/example")
    assert not metadata.package_dir.is_absolute()
    assert metadata.package_dir.as_posix() == "src/example"
