"""Representative setuptools consumers for artifact and source-cleanliness tests."""

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

from setuptools_git_metadata.template import standard_template


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "consumer"
    package = root / "src/example"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools>=80"]
build-backend = "setuptools.build_meta"
[project]
name = "metadata-example"
version = "1.2.3"
[tool.setuptools.packages.find]
where = ["src"]
[tool.setuptools.package-data]
example = ["*.json", "data.txt", "py.typed"]
[tool.setuptools-git-metadata]
package = "example"
""",
        encoding="utf-8",
    )
    (root / "README.md").write_text("Example package\n", encoding="utf-8")
    (root / "MANIFEST.in").write_text("include README.md\nexclude excluded.txt\n", encoding="utf-8")
    (root / ".gitignore").write_text(
        "build/\ndist/\n*.egg-info/\n__pycache__/\nignored.txt\n", encoding="utf-8"
    )
    (root / "excluded.txt").write_text("excluded", encoding="utf-8")
    (root / "ignored.txt").write_text("ignored", encoding="utf-8")
    loader = standard_template() + '\nCUSTOM_DISPLAY = "application-owned"\n'
    (package / "_version.py").write_bytes(loader.replace("\n", "\r\n").encode("utf-8"))
    (package / "__init__.py").write_text(
        "from ._version import PACKAGE_VERSION\n", encoding="utf-8"
    )
    (package / "data.txt").write_text("package data", encoding="utf-8")
    (package / "py.typed").touch()
    for args in [
        ("init", "-b", "main"),
        ("config", "user.name", "Fixture"),
        ("config", "user.email", "fixture@example.invalid"),
        ("add", "."),
        ("commit", "-m", "fixture"),
        ("tag", "v9.9.9"),
    ]:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    return root


def run(root, *args, env=None):
    result = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def build(root, out, kind, env=None):
    run(
        root,
        sys.executable,
        "-m",
        "build",
        "--no-isolation",
        "--outdir",
        str(out),
        "--" + kind,
        env=env,
    )
    return next(out.glob("*.whl" if kind == "wheel" else "*.tar.gz"))


def inventory(root):
    """Include ignored/untracked source; separate ordinary backend output paths."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in Path(root).rglob("*")
        if path.is_file()
        and not any(
            part in (".git", "build", "dist", "__pycache__") or part.endswith(".egg-info")
            for part in path.relative_to(root).parts
        )
    }
