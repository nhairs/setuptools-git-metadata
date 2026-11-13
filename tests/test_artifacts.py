"""Exercise real distributions, runtime imports and source cleanliness."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import venv
import zipfile

import pytest

from pyproject_hooks import BuildBackendHookCaller

from setuptools_git_metadata.build import _loads
from tests.conftest import build, inventory, run


def wheel_resource(wheel):
    with zipfile.ZipFile(wheel) as archive:
        data = _loads(archive.read("example/_git_metadata.json").decode("utf-8"))
        loader = archive.read("example/_version.py")
        assert archive.read("example/data.txt") == b"package data"
        assert "example/py.typed" in archive.namelist()
        metadata = archive.read("metadata_example-1.2.3.dist-info/METADATA").decode("utf-8")
        assert "Version: 1.2.3" in metadata
    return data, loader


def environment_python(root):
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def install(wheel, root):
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(root)
    python = environment_python(root)
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        check=True,
        capture_output=True,
    )
    return python


def test_wheel_sdist_gitless_roundtrip(project, tmp_path):
    before = inventory(project)
    original = (project / "src/example/_version.py").read_bytes()
    env = dict(os.environ, SOURCE_DATE_EPOCH="100", PYTHONDONTWRITEBYTECODE="1")
    direct = build(project, tmp_path / "direct", "wheel", env)
    direct_data, direct_loader = wheel_resource(direct)
    assert direct_data["BUILD_GIT_DIRTY"] is False
    assert direct_data["BUILD_TIMESTAMP"] == 100
    assert direct_loader == original
    env["SOURCE_DATE_EPOCH"] = "200"
    sdist = build(project, tmp_path / "sdist", "sdist", env)
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    with tarfile.open(sdist) as archive:
        archive.extractall(unpacked, filter="data")
    source = next(unpacked.iterdir())
    assert (source / "src/example/_version.py").read_bytes() == original
    frozen = _loads((source / "src/example/_git_metadata.json").read_text(encoding="utf-8"))
    assert frozen["SOURCE_TIMESTAMP"] == frozen["SDIST_BUILD_TIMESTAMP"] == 200
    clean_env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GIT_", "BUILD_", "PACKAGE_", "SOURCE_DATE_EPOCH"))
    }
    envfree = build(source, tmp_path / "envfree", "wheel", clean_env)
    assert wheel_resource(envfree)[0]["SOURCE_TIMESTAMP"] == 200
    changed_clock = dict(clean_env, SOURCE_DATE_EPOCH="300")
    rebuilt = build(source, tmp_path / "rebuilt", "wheel", changed_clock)
    data, loader = wheel_resource(rebuilt)
    for field in (
        "PACKAGE_VERSION",
        "BUILD_VERSION",
        "BUILD_GIT_HASH",
        "BUILD_GIT_HASH_SHORT",
        "BUILD_GIT_BRANCH",
        "BUILD_GIT_DIRTY",
        "BUILD_GIT_COMMIT_TIMESTAMP",
        "SELECTED_SOURCE_DIGEST",
        "SOURCE_TIMESTAMP",
        "SDIST_BUILD_TIMESTAMP",
    ):
        assert data[field] == frozen[field], field
    assert data["BUILD_TIMESTAMP"] == data["WHEEL_BUILD_TIMESTAMP"] == 300
    assert loader == original
    assert inventory(project) == before
    assert not (project / "src/example/_git_metadata.json").exists()

    python = install(rebuilt, tmp_path / "installed")
    imported = json.loads(
        run(
            tmp_path,
            str(python),
            "-c",
            """
import json, sys
import example._version as v
assert 'setuptools_git_metadata' not in sys.modules
print(json.dumps([v.BUILD_INFO.PACKAGE_VERSION, v.BUILD_INFO.BUILD_GIT_HASH, v.BUILD_INFO.BUILD_TIMESTAMP, v.CUSTOM_DISPLAY]))
""",
        )
    )
    assert imported == ["1.2.3", data["BUILD_GIT_HASH"], 300, "application-owned"]

    # A later source distribution keeps original source/sdist times too.
    repeated_sdist = build(source, tmp_path / "resdist", "sdist", changed_clock)
    with tarfile.open(repeated_sdist) as archive:
        member = next(
            m for m in archive.getmembers() if m.name.endswith("/src/example/_git_metadata.json")
        )
        repeated = _loads(archive.extractfile(member).read().decode("utf-8"))
    assert repeated["SDIST_BUILD_TIMESTAMP"] == repeated["SOURCE_TIMESTAMP"] == 200

    config = source / "pyproject.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('version = "1.2.3"', 'version = "2.0.0"'),
        encoding="utf-8",
    )
    failure = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", str(source)],
        capture_output=True,
        text=True,
    )
    assert failure.returncode and "baked version disagrees" in failure.stdout + failure.stderr


def test_metadata_preparation_and_editable_placeholders(project, tmp_path):
    before = inventory(project)
    caller = BuildBackendHookCaller(
        str(project), "setuptools.build_meta", python_executable=sys.executable
    )
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    caller.prepare_metadata_for_build_wheel(str(metadata))
    output = tmp_path / "editable"
    output.mkdir()
    wheel = output / caller.build_editable(str(output))
    with zipfile.ZipFile(wheel) as archive:
        assert not any(path.endswith("_git_metadata.json") for path in archive.namelist())
    python = install(wheel, tmp_path / "installed-editable")
    run(
        tmp_path,
        str(python),
        "-c",
        """
import example._version as v
assert v.BUILD_INFO.PACKAGE_VERSION == '__metadata_missing__'
assert v.BUILD_INFO.BUILD_GIT_HASH == '__metadata_missing__'
assert v.BUILD_INFO.BUILD_TIMESTAMP == 0
assert v.CUSTOM_DISPLAY == 'application-owned'
""",
    )
    assert inventory(project) == before


def test_unbaked_gitless_local_artifact(project, tmp_path):
    source = tmp_path / "gitless"
    shutil.copytree(
        project, source, ignore=shutil.ignore_patterns(".git", "*.egg-info", "build", "__pycache__")
    )
    wheel = build(source, tmp_path / "local", "wheel")
    data, _ = wheel_resource(wheel)
    assert data["PACKAGE_VERSION"] == "1.2.3"
    assert data["BUILD_GIT_HASH"] is None and data["BUILD_GIT_DIRTY"] is None


def test_isolated_build_uses_actual_companion_wheel(project, tmp_path):
    """Install the real companion distribution into PEP 517's isolated backend."""
    repository = Path(__file__).resolve().parents[1]
    companion = build(repository, tmp_path / "companion", "wheel")
    with zipfile.ZipFile(companion) as archive:
        own = _loads(archive.read("setuptools_git_metadata/_git_metadata.json").decode())
        assert "setuptools_git_metadata/_version.py" in archive.namelist()
        assert own["BUILD_GIT_HASH"] == run(repository, "git", "rev-parse", "HEAD").strip()

    config = project / "pyproject.toml"
    requirement = "setuptools-git-metadata @ " + companion.as_uri()
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'requires = ["setuptools>=80"]',
            'requires = ["setuptools>=80", ' + json.dumps(requirement) + "]",
        ),
        encoding="utf-8",
    )
    # Tox installed setuptools through uv already, so isolate locally from cache.
    # This does not require network access or ambient companion PYTHONPATH.
    env = dict(os.environ, UV_OFFLINE="1")
    env.pop("PYTHONPATH", None)
    output = tmp_path / "isolated-consumer"
    run(
        project,
        sys.executable,
        "-m",
        "build",
        "--installer",
        "uv",
        "--wheel",
        "--outdir",
        str(output),
        env=env,
    )
    data, _ = wheel_resource(next(output.glob("*.whl")))
    assert data["BUILD_GIT_HASH"] is not None
    assert data["BUILD_GIT_DIRTY"] is True  # Consumer config changed after commit.


@pytest.mark.parametrize("selected", [None, ["other"], "other"])
def test_multiple_packages_default_and_subset(project, tmp_path, selected):
    config = project / "pyproject.toml"
    if selected is not None:
        config.write_text(
            config.read_text(encoding="utf-8")
            + ("package" if isinstance(selected, str) else "packages")
            + " = "
            + json.dumps(selected)
            + "\n",
            encoding="utf-8",
        )
    loader = (project / "src/example/_version.py").read_bytes()
    for package in ("other", "example/child"):
        directory = project / "src" / package
        directory.mkdir()
        (directory / "__init__.py").touch()
        (directory / "_version.py").write_bytes(loader)
    run(project, "git", "add", ".")
    run(project, "git", "commit", "-m", "multiple packages")
    before = inventory(project)
    packages = selected if selected is not None else ["example", "example.child", "other"]
    if isinstance(packages, str):
        packages = [packages]
    resources = {package.replace(".", "/") + "/_git_metadata.json" for package in packages}
    direct = build(project, tmp_path / "direct", "wheel")
    with zipfile.ZipFile(direct) as archive:
        assert {p for p in archive.namelist() if p.endswith("/_git_metadata.json")} == resources
        payloads = [archive.read(p) for p in sorted(resources)]
        assert len(set(payloads)) == 1
        assert _loads(payloads[0].decode())["BUILD_GIT_DIRTY"] is False

    sdist = build(project, tmp_path / "sdist", "sdist")
    unpacked = tmp_path / "unpacked"
    unpacked.mkdir()
    with tarfile.open(sdist) as archive:
        archive.extractall(unpacked, filter="data")
    source = next(unpacked.iterdir())
    frozen = {
        package: _loads(
            (source / "src" / package.replace(".", "/") / "_git_metadata.json").read_text(
                encoding="utf-8"
            )
        )
        for package in packages
    }
    assert all(data == frozen[packages[0]] for data in frozen.values())
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GIT_", "BUILD_", "PACKAGE_", "SOURCE_DATE_EPOCH"))
    }
    rebuilt = build(source, tmp_path / "rebuilt", "wheel", env)
    with zipfile.ZipFile(rebuilt) as archive:
        assert {p for p in archive.namelist() if p.endswith("/_git_metadata.json")} == resources
        for package in packages:
            path = package.replace(".", "/") + "/_git_metadata.json"
            data = _loads(archive.read(path).decode())
            for field in frozen[package]:
                if field not in ("BUILD_TIMESTAMP", "WHEEL_BUILD_TIMESTAMP"):
                    assert data[field] == frozen[package][field], field
    assert inventory(project) == before
    assert not list((project / "src").rglob("_git_metadata.json"))
