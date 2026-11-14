"""The generated standard loader is a self-contained, resource-aware Python module."""

import json
from pathlib import Path
import os
import subprocess
import sys
import zipfile

import pytest

from dataclasses import FrozenInstanceError

from setuptools_git_metadata._version import GitMetadata
from setuptools_git_metadata.build import MetadataBuilder, _validate_metadata
from tests.conftest import standard_template


def test_cli_exclusive_output(tmp_path: Path) -> None:
    command = [sys.executable, "-m", "setuptools_git_metadata", "template"]
    generated = subprocess.check_output(command, encoding="utf-8")
    assert generated == standard_template()
    path = tmp_path / "_version.py"
    subprocess.run([*command, "--output", str(path)], check=True)
    assert path.read_bytes() == generated.encode("utf-8")
    path.write_bytes(b"application owned")
    assert subprocess.run([*command, "--output", str(path)], capture_output=True).returncode != 0
    assert path.read_bytes() == b"application owned"


def runtime(root: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(root))
    return subprocess.run(
        [sys.executable, "-c", "import example._version as v; print(v.BUILD_INFO.PACKAGE_VERSION)"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )


def test_runtime_absent_and_invalid_json(project: Path, tmp_path: Path) -> None:
    root = project / "src"
    assert runtime(root).returncode == 0
    data_dir = tmp_path / "data"
    MetadataBuilder(project, "src/example").write_metadata(data_dir, wheel=True)
    valid = json.loads((data_dir / "_git_metadata.json").read_text(encoding="utf-8"))
    sidecar = root / "example/_git_metadata.json"
    for invalid in (
        "{bad",
        "{}",
        '{"schema_version":1,"schema_version":1}',
        json.dumps(dict(valid, schema_version=True)),
        json.dumps(dict(valid, schema_version=2)),
        json.dumps({key: value for key, value in valid.items() if key != "BUILD_GIT_HASH"}),
    ):
        sidecar.write_text(invalid, encoding="utf-8")
        assert runtime(root).returncode != 0
    sidecar.write_text(json.dumps(dict(valid, UNRECOGNIZED="ignored")), encoding="utf-8")
    assert runtime(root).returncode == 0
    for data in (
        dict(valid, BUILD_GIT_HASH="field-validation-is-build-only"),
        dict(valid, BUILD_GIT_DIRTY=1),
        dict(valid, BUILD_TIMESTAMP=True),
        dict(valid, BUILD_TIMESTAMP=float("nan")),
    ):
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        assert runtime(root).returncode == 0
        with pytest.raises(ValueError):
            _validate_metadata(data)


def test_zip_resource_import(project: Path, tmp_path: Path) -> None:
    MetadataBuilder(project, "src/example").write_metadata(project / "src/example", wheel=True)
    archive = tmp_path / "example.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in (project / "src/example").iterdir():
            if path.is_file():
                output.write(path, "example/" + path.name)
    env = dict(os.environ, PYTHONPATH=str(archive))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import example; assert example.BUILD_INFO.PACKAGE_VERSION == '1.2.3'",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_typed_metadata_defaults_and_properties() -> None:
    info = GitMetadata()
    assert info.PACKAGE_VERSION == info.BUILD_GIT_HASH == "__metadata_missing__"
    assert info.BUILD_GIT_BRANCH is info.BUILD_GIT_DIRTY is None
    assert info.SDIST_BUILD_TIMESTAMP is info.WHEEL_BUILD_TIMESTAMP is None
    assert info.BUILD_TIMESTAMP == info.SOURCE_TIMESTAMP == 0
    assert info.VERSION_INFO_SHORT == info.BUILD_VERSION
    assert info.VERSION_INFO == f"{info.BUILD_VERSION}@{info.BUILD_GIT_HASH_SHORT}"
    assert str(info.BUILD_DATETIME) == "1970-01-01 00:00:00"
    with pytest.raises(FrozenInstanceError):
        setattr(info, "BUILD_VERSION", "changed")


def test_runtime_exports_model_and_build_info() -> None:
    namespace = {}
    exec("from setuptools_git_metadata._version import *", namespace)
    assert "PACKAGE_VERSION" not in namespace
    assert "BUILD_GIT_HASH" not in namespace
    assert "VERSION_INFO_SHORT" not in namespace
    assert namespace["GitMetadata"] is GitMetadata
    assert set(namespace) - {"__builtins__"} == {"GitMetadata", "BUILD_INFO"}
    assert {
        "dataclass",
        "fields",
        "datetime",
        "timezone",
        "resources",
        "json",
        "Final",
        "Optional",
    }.isdisjoint(namespace)
