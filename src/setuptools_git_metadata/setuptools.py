"""Explicit setuptools command adapters; no global activation."""

from pathlib import Path
import tomllib
from setuptools.command.build_py import build_py as BaseBuild
from setuptools.command.sdist import sdist as BaseSdist
from .core import ProjectMetadata


def project(command):
    root = Path.cwd()
    config = tomllib.loads((root / "pyproject.toml").read_text())
    settings = config.get("tool", {}).get("setuptools-git-metadata", {})
    package = settings.get("package")
    if not isinstance(package, str) or not package:
        raise ValueError("tool.setuptools-git-metadata.package is required")
    build = command if isinstance(command, BaseBuild) else command.get_finalized_command("build_py")
    if package not in (build.packages or ()):
        raise ValueError(f"configured package is not declared by setuptools: {package}")
    package_dir = build.get_package_dir(package)
    return package, ProjectMetadata(root, package_dir)


class build_py(BaseBuild):  # pylint: disable=invalid-name
    def run(self):
        package, metadata = project(self)
        metadata.validate_configuration()
        super().run()
        if not self.editable_mode:
            metadata.render(Path(self.build_lib).joinpath(*package.split(".")), wheel=True)


class sdist(BaseSdist):  # pylint: disable=invalid-name
    def make_release_tree(self, base_dir, files):
        _, metadata = project(self)
        metadata.validate_configuration()
        super().make_release_tree(base_dir, files)
        metadata.render(Path(base_dir) / metadata.package_dir)
