"""Collect and stage static version metadata without editing package sources."""

import hashlib
import io
import json
import shutil
import sys
import tarfile
import tempfile
import os
from pathlib import Path
import subprocess
import time

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from .schema import _loads, _validate


class ProjectMetadata:
    """Collect one source identity and stage it in the selected package directories."""

    def __init__(self, root, package_dirs):
        """Resolve package directories within the source root."""
        self.root = Path(root).resolve()
        if isinstance(package_dirs, (str, Path)):
            package_dirs = [package_dirs]
        self.package_dirs = []
        for package_dir in package_dirs:
            resolved = (self.root / package_dir).resolve()
            if not resolved.is_relative_to(self.root):
                raise ValueError("package directory must be inside source tree")
            self.package_dirs.append(resolved.relative_to(self.root))

    def git(self, *args):
        """Run a Git query in the source root and return stripped text."""
        return subprocess.check_output(
            ["git", *args], cwd=self.root, text=True, stderr=subprocess.DEVNULL, timeout=30
        ).strip()

    def selected_dirty(self):  # pylint: disable=too-many-locals
        """Fresh backend manifests for current and HEAD with current config."""
        all_git_paths = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=self.root,
            timeout=30,
        ).split(b"\0")
        if any(b"\n" in path or b"\r" in path for path in all_git_paths):
            raise ValueError(
                "newline filenames cannot be represented safely by setuptools manifests"
            )

        generated = {(path / "_git_metadata.json").as_posix() for path in self.package_dirs}

        def selected(root):
            with tempfile.TemporaryDirectory() as td:
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "from setuptools import setup; setup()",
                        "egg_info",
                        "--egg-base",
                        td,
                    ],
                    cwd=root,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                manifest = next(Path(td).glob("*.egg-info/SOURCES.txt"))
                paths = manifest.read_text(encoding="utf-8").splitlines()
                return {
                    p
                    for p in paths
                    if ".egg-info/" not in p and p not in generated and (root / p).is_file()
                }

        with tempfile.TemporaryDirectory() as td:
            head = Path(td) / "head"
            head.mkdir()
            prefix = self.git("rev-parse", "--show-prefix")
            tree = "HEAD:" + prefix.rstrip("/") if prefix else "HEAD"
            archive = subprocess.check_output(["git", "archive", tree], cwd=self.root, timeout=30)
            with tarfile.open(fileobj=io.BytesIO(archive)) as archive_file:
                archive_file.extractall(head, filter="data")
            for control in ("pyproject.toml", "MANIFEST.in", "setup.cfg", "setup.py", ".gitignore"):
                if (self.root / control).exists():
                    shutil.copy(self.root / control, head / control)
                elif (head / control).is_file():
                    (head / control).unlink()
            paths = selected(self.root) | selected(head)

            def git_paths(*args):
                output = subprocess.check_output(["git", *args, "-z"], cwd=self.root)
                return {os.fsdecode(p) for p in output.split(b"\0") if p}

            changed = git_paths("diff", "--name-only", "--relative", "HEAD")
            changed |= git_paths("ls-files", "--others", "--exclude-standard")
            for path in paths:
                if not (self.root / path).resolve().is_relative_to(self.root):
                    raise ValueError("selected source input escapes project root")
            relevant = sorted(paths & changed)
            digest = hashlib.sha256()
            for path in sorted(paths):
                if (self.root / path).is_file():
                    digest.update(
                        path.encode()
                        + b"\0"
                        + hashlib.sha256((self.root / path).read_bytes()).digest()
                    )
            return bool(relevant), digest.hexdigest()

    def validate_baked(self, data, version):
        """Validate baked metadata against the declared project version."""
        _validate(data)
        if data["PACKAGE_VERSION"] != version:
            raise ValueError("baked version disagrees with project.version")

    def validate_configuration(self):
        """Return the authoritative static version or reject unsupported settings."""
        config = tomllib.loads((self.root / "pyproject.toml").read_text(encoding="utf-8"))
        if (
            config.get("tool", {}).get("setuptools-git-metadata", {}).get("version-mode", "static")
            != "static"
        ):
            raise NotImplementedError("branch-derived versions are deferred")
        version = config.get("project", {}).get("version")
        if not isinstance(version, str) or not version:
            raise ValueError("a static project.version is required")
        return version

    def payload(self, event=None):
        """Preserve consistent baked metadata or collect live source identity."""
        version = self.validate_configuration()
        data = None
        for package_dir in self.package_dirs:
            baked = self.root / package_dir / "_git_metadata.json"
            if baked.exists():
                candidate = _loads(baked.read_text(encoding="utf-8"))
                self.validate_baked(candidate, version)
                if data is not None and candidate != data:
                    raise ValueError("baked metadata disagrees between packages")
                data = candidate
        if data is not None:
            return data
        now = self.event_time() if event is None else event
        try:
            full = self.git("rev-parse", "HEAD")
            prefix = self.git("rev-parse", "--show-prefix")
            self.git("cat-file", "-e", "HEAD:" + prefix + "pyproject.toml")
            branch = (
                self.git("symbolic-ref", "--short", "-q", "HEAD")
                if self.git("rev-parse", "--abbrev-ref", "HEAD") != "HEAD"
                else None
            )
            commit_time = int(self.git("show", "-s", "--format=%ct", "HEAD"))
        except (subprocess.CalledProcessError, FileNotFoundError):
            full, branch, commit_time = None, None, None
            dirty, source_digest = None, None
        else:
            dirty, source_digest = self.selected_dirty()
        return {
            "PACKAGE_VERSION": version,
            "BUILD_VERSION": version,
            "BUILD_GIT_HASH": full,
            "BUILD_GIT_HASH_SHORT": full[:8] if full else None,
            "BUILD_GIT_BRANCH": branch,
            "BUILD_GIT_COMMIT_TIMESTAMP": commit_time,
            "BUILD_GIT_DIRTY": dirty,
            "SELECTED_SOURCE_DIGEST": source_digest,
            "BUILD_TIMESTAMP": now,
            "SOURCE_TIMESTAMP": now,
        }

    def render(self, directories, wheel=False):
        """Capture one artifact event and write identical metadata to each destination."""
        event = self.event_time()
        data = self.payload(event)
        data["WHEEL_BUILD_TIMESTAMP"] = event if wheel else None
        data["BUILD_TIMESTAMP"] = event
        if not wheel:
            if data.get("SDIST_BUILD_TIMESTAMP") is None:
                data["SDIST_BUILD_TIMESTAMP"] = event
        else:
            data.setdefault("SDIST_BUILD_TIMESTAMP", None)
        data["schema_version"] = 1
        _validate(data)
        if isinstance(directories, Path):
            directories = [directories]
        content = json.dumps(data, sort_keys=True)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            self.atomic_write(directory / "_git_metadata.json", content)

    @staticmethod
    def atomic_write(path, content):
        """Replace a staged file atomically without changing linked source files."""
        # Replace copied files instead of editing a possibly hardlinked inode.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(content)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def event_time():
        """Return the current artifact epoch, respecting SOURCE_DATE_EPOCH."""
        raw = os.environ.get("SOURCE_DATE_EPOCH")
        if raw is None:
            return int(time.time())
        if not raw.isascii() or not raw.isdigit():
            raise ValueError("SOURCE_DATE_EPOCH must be a nonnegative integer")
        return int(raw)
