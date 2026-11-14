"""Activate staged metadata commands for configured setuptools projects."""

from pathlib import Path
from collections.abc import Iterable
from typing import cast
from setuptools import Command, Distribution
from setuptools.command.build_py import build_py as BaseBuild
from setuptools.command.sdist import sdist as BaseSdist
from .build import MetadataBuilder, tomllib


def activate(distribution: Distribution) -> None:
    """Register command adapters only when this project opts in."""
    path = Path("pyproject.toml")
    if not path.is_file():
        return
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    if "setuptools-git-metadata" in config.get("tool", {}):
        distribution.cmdclass.setdefault("build_py", build_py)
        distribution.cmdclass.setdefault("sdist", sdist)

    return


def resolve_project(command: Command) -> tuple[list[str], MetadataBuilder]:
    """Resolve selected setuptools packages and their shared source metadata."""
    root = Path.cwd()
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    settings = config.get("tool", {}).get("setuptools-git-metadata", {})
    build = (
        command
        if isinstance(command, BaseBuild)
        else cast(BaseBuild, command.get_finalized_command("build_py"))
    )
    declared = build.packages or []
    if "package" in settings and "packages" in settings:
        raise ValueError("configure either package or packages, not both")
    packages = settings.get("packages", list(declared))
    if "package" in settings:
        packages = [settings["package"]]
    if not isinstance(packages, list) or any(not isinstance(p, str) or not p for p in packages):
        raise ValueError("tool.setuptools-git-metadata.packages must be a list of package names")
    for package in packages:
        if package not in declared:
            raise ValueError(f"configured package is not declared by setuptools: {package}")
    packages = list(dict.fromkeys(packages))
    return packages, MetadataBuilder(root, [build.get_package_dir(p) for p in packages])


class build_py(BaseBuild):  # pylint: disable=invalid-name
    """Add shared metadata to each selected package in the wheel staging tree."""

    def run(self) -> None:
        """Build package files and stage metadata for regular installations."""
        packages, metadata = resolve_project(self)
        metadata.validate_configuration()
        super().run()
        if packages and not self.editable_mode:
            directories = [
                Path(self.build_lib).joinpath(*package.split(".")) for package in packages
            ]
            metadata.write_metadata(directories, wheel=True)

        return


class sdist(BaseSdist):  # pylint: disable=invalid-name
    """Include shared metadata in the selected packages of a source archive."""

    def make_release_tree(self, base_dir: str, files: Iterable[str]) -> None:
        """Populate the release tree before adding baked metadata."""
        _, metadata = resolve_project(self)
        metadata.validate_configuration()
        super().make_release_tree(base_dir, files)
        if metadata.package_dirs:
            metadata.write_metadata([Path(base_dir) / path for path in metadata.package_dirs])

        return
