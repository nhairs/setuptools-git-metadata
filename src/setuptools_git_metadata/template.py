"""Emit the standard, self-contained runtime loader explicitly."""

from importlib import resources


def standard_template():
    """Return a stdlib-only loader supporting package runtimes Python 3.9+."""
    package = resources.files("setuptools_git_metadata")
    schema = package.joinpath("schema.py").read_text(encoding="utf-8")
    runtime = package.joinpath("runtime.py.txt").read_text(encoding="utf-8")
    return schema + runtime
