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

from pyproject_hooks import BuildBackendHookCaller

from setuptools_git_metadata.schema import _loads
from tests.conftest import build, inventory, run


def wheel_resource(wheel):
    with zipfile.ZipFile(wheel) as archive:
        data = _loads(archive.read("example/_provenance.json").decode("utf-8"))
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
    frozen = _loads((source / "src/example/_provenance.json").read_text(encoding="utf-8"))
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
    assert not (project / "src/example/_provenance.json").exists()

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
print(json.dumps([v.PACKAGE_VERSION, v.BUILD_GIT_HASH, v.BUILD_TIMESTAMP, v.CUSTOM_DISPLAY]))
""",
        )
    )
    assert imported == ["1.2.3", data["BUILD_GIT_HASH"], 300, "application-owned"]

    # A later source distribution keeps original source/sdist times too.
    repeated_sdist = build(source, tmp_path / "resdist", "sdist", changed_clock)
    with tarfile.open(repeated_sdist) as archive:
        member = next(
            m for m in archive.getmembers() if m.name.endswith("/src/example/_provenance.json")
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
        assert not any(path.endswith("_provenance.json") for path in archive.namelist())
    python = install(wheel, tmp_path / "installed-editable")
    run(
        tmp_path,
        str(python),
        "-c",
        """
import example._version as v
assert v.PACKAGE_VERSION == ''
assert v.BUILD_GIT_HASH is None
assert v.BUILD_TIMESTAMP == 0
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
