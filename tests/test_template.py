"""The generated standard loader is a self-contained, resource-aware Python module."""

import json
import os
import subprocess
import sys
import zipfile

import pytest

from setuptools_git_metadata.core import ProjectMetadata
from setuptools_git_metadata.template import standard_template


def test_cli_exclusive_output(tmp_path):
    command = [sys.executable, "-m", "setuptools_git_metadata", "template"]
    generated = subprocess.check_output(command)
    assert generated.decode() == standard_template()
    path = tmp_path / "_version.py"
    subprocess.run([*command, "--output", str(path)], check=True)
    assert path.read_bytes() == generated
    path.write_bytes(b"application owned")
    assert subprocess.run([*command, "--output", str(path)], capture_output=True).returncode != 0
    assert path.read_bytes() == b"application owned"


def runtime(root):
    env = dict(os.environ, PYTHONPATH=str(root))
    return subprocess.run(
        [sys.executable, "-c", "import example._version as v; print(v.PACKAGE_VERSION)"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )


def test_runtime_absent_and_invalid_json(project, tmp_path):
    root = project / "src"
    assert runtime(root).returncode == 0
    data_dir = tmp_path / "data"
    ProjectMetadata(project, "src/example").render(data_dir, wheel=True)
    valid = json.loads((data_dir / "_provenance.json").read_text(encoding="utf-8"))
    sidecar = root / "example/_provenance.json"
    for invalid in (
        "{bad",
        "{}",
        '{"schema_version":1,"schema_version":1}',
        json.dumps(dict(valid, schema_version=True)),
        json.dumps(dict(valid, BUILD_GIT_DIRTY=1)),
        json.dumps(dict(valid, BUILD_TIMESTAMP=True)),
        json.dumps(dict(valid, BUILD_TIMESTAMP=float("nan"))),
    ):
        sidecar.write_text(invalid, encoding="utf-8")
        assert runtime(root).returncode != 0
    sidecar.write_text(json.dumps(dict(valid, UNRECOGNIZED="ignored")), encoding="utf-8")
    assert runtime(root).returncode == 0


def test_zip_resource_import(project, tmp_path):
    ProjectMetadata(project, "src/example").render(project / "src/example", wheel=True)
    archive = tmp_path / "example.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in (project / "src/example").iterdir():
            if path.is_file():
                output.write(path, "example/" + path.name)
    env = dict(os.environ, PYTHONPATH=str(archive))
    result = subprocess.run(
        [sys.executable, "-c", "import example; assert example.PACKAGE_VERSION == '1.2.3'"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
