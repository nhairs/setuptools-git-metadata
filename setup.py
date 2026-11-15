"""Bootstrap this project's local setuptools metadata commands."""

from pathlib import Path
import sys

from setuptools import setup

sys.path.insert(0, str(Path(__file__).parent / "src"))

# The commands must be available before this distribution is installed.
# pylint: disable-next=wrong-import-position
from setuptools_git_metadata.setuptools import (
    build_py,
    sdist,
)

setup(cmdclass={"build_py": build_py, "sdist": sdist})
