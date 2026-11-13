"""Emit the standard, self-contained runtime loader explicitly."""

from importlib import resources


def standard_template():
    """Return a stdlib-only loader supporting package runtimes Python 3.9+."""
    package = resources.files("setuptools_git_metadata")
    return package.joinpath("_version.py").read_text(encoding="utf-8")
