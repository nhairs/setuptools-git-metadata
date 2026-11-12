# setuptools-git-metadata

Include your package's version, Git commit, branch and build timestamps in source distributions and wheels. Import those values through a committed, customisable `_version.py`.

The build tool requires Python 3.10.12+, 3.11.4+, or 3.12+, and setuptools 80 or later. Git is required when collecting commit information. The generated runtime loader supports Python 3.9 or later.

## Configure your project

Add the build requirement and enable metadata generation:

```toml
[build-system]
requires = ["setuptools>=80", "setuptools-git-metadata"]
build-backend = "setuptools.build_meta"

[project]
name = "example"
version = "1.2.3"

[tool.setuptools-git-metadata]
```

Metadata is included automatically in every package detected by setuptools. To select specific packages, add their import names:

```toml
[tool.setuptools-git-metadata]
packages = ["example", "example.utilities"]
```

The declared `project.version` determines the package version. Projects that customise setuptools' `build_py` or `sdist` commands must integrate the metadata commands with their overrides.

This development version is available from source. Build its wheel with `uv build --wheel`, then replace the `setuptools-git-metadata` requirement with `setuptools-git-metadata @ file:///ABSOLUTE_PATH/setuptools_git_metadata-0.1.0.dev0-py3-none-any.whl`.

## Add the runtime loader

Install the build tool in your development environment, then create a loader in each package where you want to import the version information:

```sh
python3 -m setuptools_git_metadata template --output src/example/_version.py
```

Commit the generated file. You can customise its display strings and add application helpers. The command refuses to overwrite an existing file. To print the template for comparison, run:

```sh
python3 -m setuptools_git_metadata template
```

Build your distributions using your usual setuptools build command. Each selected package receives `_git_metadata.json` automatically. Keep this generated file out of your development checkout.

Import version information from an installed package:

```python
from example._version import PACKAGE_VERSION, BUILD_GIT_HASH
```

Without generated metadata, the loader exposes empty version strings, unavailable Git information and a build timestamp of zero. This includes editable installs from a development checkout.

## Available metadata

| Runtime fields | Meaning |
| --- | --- |
| `PACKAGE_VERSION`, `BUILD_VERSION` | Declared project version |
| `BUILD_GIT_HASH`, `BUILD_GIT_HASH_SHORT` | Full Git commit hash and its first eight characters |
| `BUILD_GIT_BRANCH` | Branch name, or `None` when unavailable |
| `BUILD_GIT_DIRTY` | Whether selected source inputs have changed |
| `BUILD_GIT_COMMIT_TIMESTAMP` | Git commit time |
| `SELECTED_SOURCE_DIGEST` | Digest of the selected source inputs |
| `SOURCE_TIMESTAMP` | Original source metadata time |
| `SDIST_BUILD_TIMESTAMP` | Original source distribution build time |
| `WHEEL_BUILD_TIMESTAMP` | Wheel build time |
| `BUILD_TIMESTAMP`, `BUILD_DATETIME` | Current artifact build time |

The loader also provides `VERSION_INFO_SHORT`, `VERSION_INFO`, `VERSION_INFO_LONG` and `VERSION_INFO_FULL` display strings.

Wheels built from a source distribution retain its version, commit, branch and source timestamps. Their wheel build time reflects the new build. Set `SOURCE_DATE_EPOCH` to a nonnegative integer to control the artifact build time.

A source tree without Git information or previously generated metadata produces unavailable Git fields. Invalid metadata and a version that conflicts with previously generated metadata cause the build to fail.

## Develop and test

```sh
uv sync --group dev
uvx tox -e lint
uvx tox
```

Tox covers CPython 3.10–3.15 and PyPy 3.10–3.12. GitHub Actions runs the suite on Ubuntu, macOS and Windows.
