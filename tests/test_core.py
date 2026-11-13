"""Build-side identity, strict provenance and selection behavior."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from setuptools_git_metadata.build import MetadataBuilder
from setuptools_git_metadata.build import _loads, _validate
from tests.conftest import inventory


def test_selected_source_changes(project):
    metadata = MetadataBuilder(project, "src/example")
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
        assert metadata.payload()["BUILD_GIT_DIRTY"] is True, name
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
    metadata = MetadataBuilder(clone, "src/example")
    assert metadata.payload()["BUILD_GIT_DIRTY"] is False
    subprocess.run(["git", "checkout", "--detach"], cwd=clone, check=True, capture_output=True)
    assert metadata.payload()["BUILD_GIT_BRANCH"] is None


def test_selector_failure_not_missing_git(project, monkeypatch):
    metadata = MetadataBuilder(project, "src/example")

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
    MetadataBuilder.atomic_write(staged, "replacement")
    assert original.read_text(encoding="utf-8") == "original"
    assert staged.read_text(encoding="utf-8") == "replacement"


@pytest.mark.parametrize("invalid", ["-1", "", "false", "1.0", "１２"])
def test_invalid_clock(invalid, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", invalid)
    with pytest.raises(ValueError, match="SOURCE_DATE_EPOCH"):
        MetadataBuilder.build_timestamp()


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
        MetadataBuilder(project, "src/example").render(target)
    assert not target.exists()


def test_baked_priority_and_epoch_zero(project, tmp_path, monkeypatch):
    metadata = MetadataBuilder(project, "src/example")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    metadata.render(tmp_path / "first")
    baked = _loads((tmp_path / "first/_git_metadata.json").read_text(encoding="utf-8"))
    assert baked["BUILD_GIT_DIRTY"] is False and baked["SOURCE_TIMESTAMP"] == 0
    (project / "src/example/_git_metadata.json").write_text(json.dumps(baked), encoding="utf-8")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "100")
    metadata.render(tmp_path / "wheel", wheel=True)
    rebuilt = _loads((tmp_path / "wheel/_git_metadata.json").read_text(encoding="utf-8"))
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
    MetadataBuilder(project, "src/example").render(tmp_path / "payload")
    data = _loads((tmp_path / "payload/_git_metadata.json").read_text(encoding="utf-8"))
    data[field] = True
    with pytest.raises(ValueError):
        _validate(data)


def test_strict_json():
    for text in ('{"schema_version":1,"schema_version":1}', '{"x":NaN}', "{bad", "{}"):
        with pytest.raises(ValueError):
            _loads(text)


def test_package_escape(tmp_path):
    with pytest.raises(ValueError, match="inside source"):
        MetadataBuilder(tmp_path, "../outside")


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
    metadata = MetadataBuilder(nested, "src/example")
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
        MetadataBuilder(project, "src/example").payload()


def test_absolute_package_directory_is_staged_as_relative(project):
    metadata = MetadataBuilder(project, project / "src/example")
    assert metadata.package_dirs == [Path("src/example")]


def test_automatic_commands_and_explicit_overrides(project, monkeypatch):
    from setuptools import Distribution
    from setuptools.command.build_py import build_py as BaseBuild

    from setuptools_git_metadata.setuptools import build_py, sdist

    monkeypatch.chdir(project)
    automatic = Distribution()
    assert automatic.cmdclass["build_py"] is build_py
    assert automatic.cmdclass["sdist"] is sdist
    custom = Distribution({"cmdclass": {"build_py": BaseBuild}})
    assert custom.cmdclass["build_py"] is BaseBuild


def test_unconfigured_project_keeps_commands(tmp_path, monkeypatch):
    from setuptools import Distribution

    monkeypatch.chdir(tmp_path)
    assert "build_py" not in Distribution().cmdclass
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "unrelated"\n', encoding="utf-8")
    assert "build_py" not in Distribution().cmdclass


def test_multiple_packages_preserve_one_baked_payload(project, tmp_path, monkeypatch):
    other = project / "src/other"
    other.mkdir()
    (other / "__init__.py").touch()
    metadata = MetadataBuilder(project, ["src/example", "src/other"])
    epochs = iter((100, 200, 300))
    monkeypatch.setattr(metadata, "build_timestamp", lambda: next(epochs))
    destinations = [tmp_path / "first", tmp_path / "second"]
    metadata.render(destinations)
    raw = (destinations[0] / "_git_metadata.json").read_bytes()
    assert raw == (destinations[1] / "_git_metadata.json").read_bytes()
    baked = _loads(raw.decode())
    assert baked["SOURCE_TIMESTAMP"] == baked["BUILD_TIMESTAMP"] == 100

    # A baked resource in any selected package takes precedence over live Git.
    (other / "_git_metadata.json").write_bytes(raw)
    assert metadata.payload() == baked
    conflicting = dict(baked, BUILD_GIT_BRANCH="conflicting")
    (project / "src/example/_git_metadata.json").write_text(
        json.dumps(conflicting), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="between packages"):
        metadata.payload()
