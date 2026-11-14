"""Build-side identity, strict provenance and selection behavior."""

import json
import typing
import os
from pathlib import Path
import subprocess

import pytest

from setuptools_git_metadata.build import MetadataBuilder
from setuptools_git_metadata.build import _loads, validate_metadata
from tests.conftest import inventory


def test_selected_source_changes(project: Path) -> None:
    """Classify selected edits, deletions and additions while checking ignored inputs."""
    ### Setup and clean baseline
    metadata = MetadataBuilder(project, "src/example")
    before = inventory(project)
    original = metadata.generate_metadata()
    assert original["PACKAGE_VERSION"] == original["BUILD_VERSION"] == "1.2.3"
    full_hash = original["BUILD_GIT_HASH"]
    assert isinstance(full_hash, str)
    assert len(full_hash) == 40
    assert original["BUILD_GIT_DIRTY"] is False
    ### Excluded and ignored edits
    for name in ("excluded.txt", "ignored.txt"):
        (project / name).write_text("changed", encoding="utf-8")
        assert metadata.generate_metadata()["BUILD_GIT_DIRTY"] is False
    ### Selected tracked deletion
    data = project / "src/example/data.txt"
    data.unlink()
    assert metadata.generate_metadata()["BUILD_GIT_DIRTY"] is True
    data.write_text("package data", encoding="utf-8")
    ### Selected untracked additions
    for name in ("new.py", "with space.py", "café.py"):
        path = project / "src/example" / name
        path.write_text("# selected untracked", encoding="utf-8")
        assert metadata.generate_metadata()["BUILD_GIT_DIRTY"] is True, name
        path.unlink()
    ### Custom loader edits affect source identity
    template = project / "src/example/_version.py"
    template.write_bytes(template.read_bytes() + b'\nCUSTOM = "changed"\n')
    changed = metadata.generate_metadata()
    assert changed["BUILD_GIT_DIRTY"] is True
    assert changed["SELECTED_SOURCE_DIGEST"] != original["SELECTED_SOURCE_DIGEST"]
    assert "ignored.txt" in before  # Ignored source is actually inventoried.

    return


def test_detached_and_shallow(project: Path, tmp_path: Path) -> None:
    """Read shallow-clone identity and allow an unavailable branch on detached HEAD."""
    ### Create a shallow clone
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth=1", "--no-local", project.as_uri(), str(clone)],
        check=True,
        capture_output=True,
    )
    ### Read the shallow source identity
    metadata = MetadataBuilder(clone, "src/example")
    assert metadata.generate_metadata()["BUILD_GIT_DIRTY"] is False
    ### Detach HEAD and check branch availability
    subprocess.run(["git", "checkout", "--detach"], cwd=clone, check=True, capture_output=True)
    assert metadata.generate_metadata()["BUILD_GIT_BRANCH"] is None

    return


def test_selector_failure_not_missing_git(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Propagate a source-selection failure after Git identity was successfully read."""
    metadata = MetadataBuilder(project, "src/example")

    def failed() -> typing.NoReturn:
        raise subprocess.CalledProcessError(1, ["selection"])

    monkeypatch.setattr(metadata, "selected_dirty", failed)
    with pytest.raises(subprocess.CalledProcessError):
        metadata.generate_metadata()

    return


def test_hardlink_write_does_not_change_original(tmp_path: Path) -> None:
    """Replace a staged hardlink while preserving the original source bytes."""
    original = tmp_path / "original.json"
    original.write_text("original", encoding="utf-8")
    staged = tmp_path / "staged.json"
    os.link(original, staged)
    MetadataBuilder.atomic_write(staged, "replacement")
    assert original.read_text(encoding="utf-8") == "original"
    assert staged.read_text(encoding="utf-8") == "replacement"

    return


@pytest.mark.parametrize("invalid", ["-1", "", "false", "1.0", "１２"])
def test_invalid_clock(invalid: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject each invalid reproducible-build timestamp supplied by the parameter list."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", invalid)
    with pytest.raises(ValueError, match="SOURCE_DATE_EPOCH"):
        MetadataBuilder.build_timestamp()

    return


def test_unknown_mode_before_output(project: Path, tmp_path: Path) -> None:
    """Reject unsupported version modes before creating the output directory."""
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
        MetadataBuilder(project, "src/example").write_metadata(target)
    assert not target.exists()

    return


def test_baked_priority_and_epoch_zero(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve baked identity and epoch zero while refreshing wheel timestamps."""
    ### Setup
    metadata = MetadataBuilder(project, "src/example")
    ### Capture a valid epoch-zero source event
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    metadata.write_metadata(tmp_path / "first")
    baked = _loads((tmp_path / "first/_git_metadata.json").read_text(encoding="utf-8"))
    assert baked["BUILD_GIT_DIRTY"] is False and baked["SOURCE_TIMESTAMP"] == 0
    (project / "src/example/_git_metadata.json").write_text(json.dumps(baked), encoding="utf-8")
    ### Refresh the wheel event while preserving baked source data
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "100")
    metadata.write_metadata(tmp_path / "wheel", wheel=True)
    rebuilt = _loads((tmp_path / "wheel/_git_metadata.json").read_text(encoding="utf-8"))
    assert rebuilt["SOURCE_TIMESTAMP"] == rebuilt["SDIST_BUILD_TIMESTAMP"] == 0
    assert rebuilt["BUILD_TIMESTAMP"] == rebuilt["WHEEL_BUILD_TIMESTAMP"] == 100
    assert rebuilt["BUILD_GIT_HASH"] == baked["BUILD_GIT_HASH"]
    ### Reject a declared-version conflict
    with pytest.raises(ValueError, match="baked version"):
        metadata.validate_baked_metadata(baked, "2.0.0")

    return


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
def test_bool_is_not_timestamp_or_schema(project: Path, tmp_path: Path, field: str) -> None:
    """Reject booleans in schema-version and timestamp integer fields."""
    MetadataBuilder(project, "src/example").write_metadata(tmp_path / "payload")
    data = _loads((tmp_path / "payload/_git_metadata.json").read_text(encoding="utf-8"))
    data[field] = True
    with pytest.raises(ValueError):
        validate_metadata(data)

    return


def test_strict_json() -> None:
    """Reject duplicate keys, nonfinite constants and incomplete JSON metadata."""
    for text in ('{"schema_version":1,"schema_version":1}', '{"x":NaN}', "{bad", "{}"):
        with pytest.raises(ValueError):
            _loads(text)

    return


def test_package_escape(tmp_path: Path) -> None:
    """Reject a package directory that resolves outside the source root."""
    with pytest.raises(ValueError, match="inside source"):
        MetadataBuilder(tmp_path, "../outside")

    return


def test_nested_project_uses_relative_git_paths(project: Path) -> None:
    """Restrict selected-source dirtiness to a nested project's distribution inputs."""
    import shutil

    ### Move the consumer into a larger repository
    nested = project / "packages" / "example"
    nested.mkdir(parents=True)
    for path in list(project.iterdir()):
        if path.name not in (".git", "packages"):
            shutil.move(str(path), nested / path.name)
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "nested project"], cwd=project, check=True, capture_output=True
    )
    ### Check edits outside and inside the selected project
    metadata = MetadataBuilder(nested, "src/example")
    assert metadata.generate_metadata()["BUILD_GIT_DIRTY"] is False
    (project / "outside.txt").write_text("not a distribution input", encoding="utf-8")
    assert metadata.generate_metadata()["BUILD_GIT_DIRTY"] is False
    (nested / "README.md").write_text("selected", encoding="utf-8")
    assert metadata.generate_metadata()["BUILD_GIT_DIRTY"] is True

    return


@pytest.mark.skipif(os.name == "nt", reason="Windows prohibits newline characters in filenames")
def test_newline_filename_has_explicit_error(project: Path) -> None:
    """Reject filenames that cannot be represented by the line-based source manifest."""
    (project / "src/example/new\nline.py").write_text(
        "# cannot represent in SOURCES.txt", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="newline filenames"):
        MetadataBuilder(project, "src/example").generate_metadata()

    return


def test_absolute_package_directory_is_staged_as_relative(project: Path) -> None:
    """Normalize an absolute package directory to a source-relative staging path."""
    metadata = MetadataBuilder(project, project / "src/example")
    assert metadata.package_dirs == [Path("src/example")]

    return


def test_automatic_commands_and_explicit_overrides(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Activate configured adapters and retain explicitly supplied command classes."""
    from setuptools import Distribution
    from setuptools.command.build_py import build_py as BaseBuild

    from setuptools_git_metadata.setuptools import build_py, sdist

    monkeypatch.chdir(project)
    ### Register the default adapters
    automatic = Distribution()
    assert automatic.cmdclass["build_py"] is build_py
    assert automatic.cmdclass["sdist"] is sdist
    ### Preserve an explicit command override
    custom = Distribution({"cmdclass": {"build_py": BaseBuild}})
    assert custom.cmdclass["build_py"] is BaseBuild

    return


def test_unconfigured_project_keeps_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the default setuptools commands when plugin configuration is absent."""
    from setuptools import Distribution

    monkeypatch.chdir(tmp_path)
    assert "build_py" not in Distribution().cmdclass
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "unrelated"\n', encoding="utf-8")
    assert "build_py" not in Distribution().cmdclass

    return


def test_multiple_packages_preserve_one_baked_payload(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture one shared event and reject contradictory baked resources."""
    ### Setup two packages and a changing clock
    other = project / "src/other"
    other.mkdir()
    (other / "__init__.py").touch()
    metadata = MetadataBuilder(project, ["src/example", "src/other"])
    epochs = iter((100, 200, 300))
    monkeypatch.setattr(metadata, "build_timestamp", lambda: next(epochs))
    destinations = [tmp_path / "first", tmp_path / "second"]
    ### Capture one timestamp for every destination
    metadata.write_metadata(destinations)
    raw = (destinations[0] / "_git_metadata.json").read_bytes()
    assert raw == (destinations[1] / "_git_metadata.json").read_bytes()
    baked = _loads(raw.decode())
    assert baked["SOURCE_TIMESTAMP"] == baked["BUILD_TIMESTAMP"] == 100

    ### Read the existing payload from either package
    # A baked resource in any selected package takes precedence over live Git.
    (other / "_git_metadata.json").write_bytes(raw)
    assert metadata.generate_metadata() == baked
    ### Reject conflicting package resources
    conflicting = dict(baked, BUILD_GIT_BRANCH="conflicting")
    (project / "src/example/_git_metadata.json").write_text(
        json.dumps(conflicting), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="between packages"):
        metadata.generate_metadata()

    return


def test_git_abbreviation_can_expand_and_remain_baked(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve extended Git abbreviations through baked, Gitless wheel metadata."""
    ### Setup
    metadata = MetadataBuilder(project, "src/example")
    git = metadata.git
    full = git("rev-parse", "HEAD")

    def extended_abbreviation(*args: str) -> str:
        if args == ("rev-parse", "--short=8", full):
            return git("rev-parse", "--short=12", full)
        return git(*args)

    ### Capture an extended abbreviation from Git
    monkeypatch.setattr(metadata, "git", extended_abbreviation)
    metadata.write_metadata(tmp_path / "source")
    data = _loads((tmp_path / "source/_git_metadata.json").read_text(encoding="utf-8"))
    assert data["BUILD_GIT_HASH_SHORT"] == full[:12]
    (project / "src/example/_git_metadata.json").write_text(json.dumps(data), encoding="utf-8")

    def no_git(*args: str) -> typing.NoReturn:
        raise AssertionError(f"Baked metadata must bypass Git: {args}")

    ### Rebuild solely from baked data
    monkeypatch.setattr(metadata, "git", no_git)
    metadata.write_metadata(tmp_path / "wheel", wheel=True)
    rebuilt = _loads((tmp_path / "wheel/_git_metadata.json").read_text(encoding="utf-8"))
    assert rebuilt["BUILD_GIT_HASH_SHORT"] == full[:12]
    ### Reject invalid abbreviated prefixes
    for invalid in (full[:7], full + "0", ("0" if full[0] != "0" else "1") + full[1:]):
        with pytest.raises(ValueError, match="short hash"):
            validate_metadata(dict(data, BUILD_GIT_HASH_SHORT=invalid))

    return
