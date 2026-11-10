# setuptools-git-metadata

Bake Git provenance into setuptools distributions without generating or editing Python source in your checkout. The declared `project.version` remains authoritative. The build adapter writes a JSON resource into staged source distributions and wheels; a committed, customizable `_version.py` loads that resource at runtime.

The build tool requires Python 3.11 or later, setuptools 80 or later, and Git when collecting source identity. The standard runtime loader requires Python 3.9 or later and uses only the standard library. An installed application does not need this build tool or Git.

## Install from source

This initial development version has not been published to a package index. From a checkout, install it into your build environment:

```sh
uv pip install .
```

For an isolated consumer build before publication, build a wheel and use its absolute file URI in the consumer's build requirements:

```sh
uv build --wheel
```

For example, replace the companion requirement in the following configuration with `setuptools-git-metadata @ file:///ABSOLUTE_PATH/setuptools_git_metadata-0.1.0.dev0-py3-none-any.whl`. The wheel must be available to the environment running the build.

## Configure a consuming package

Add the companion to `build-system.requires` and explicitly select its setuptools command classes:

```toml
[build-system]
requires = ["setuptools>=80", "setuptools-git-metadata"]
build-backend = "setuptools.build_meta"

[project]
name = "example"
version = "1.2.3"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
example = ["_provenance.json"]

[tool.setuptools-git-metadata]
package = "example"
version-mode = "static"

[tool.setuptools.cmdclass]
build_py = "setuptools_git_metadata.setuptools.build_py"
sdist = "setuptools_git_metadata.setuptools.sdist"
```

Replace `example` with a declared setuptools import package. The adapter resolves its source directory through setuptools, so the distribution name and import package do not need to match. This initial interface selects one package per project.

Installing the companion does not activate global setuptools hooks. Projects that already override `build_py` or `sdist` need explicit command-class composition and validation.

The `static` mode uses `project.version`; it does not calculate versions from tags. Other version modes are reserved and raise `NotImplementedError`. The JSON resource uses schema version 1.

## Commit the runtime loader

Create the standard runtime loader explicitly:

```sh
setuptools-git-metadata template --output src/example/_version.py
```

The command creates a new file and refuses to overwrite an existing file. To inspect the template or merge it into an existing module, print it to standard output:

```sh
python -m setuptools_git_metadata template
```

Commit `_version.py` and customize its display strings and other application helpers. Build hooks never rewrite this file, replace assignments, or generate other Python source. The loader and the build tool share a generated copy of the same schema validation code, while the committed application loader has no dependency on the companion.

Do not commit the generated `_provenance.json`. A valid source-side resource is treated as baked provenance, including when the source is rebuilt inside another Git repository. Keeping a stale resource in a development checkout would deliberately retain its old identity.

Without a JSON resource, editable imports expose placeholder values: empty versions, unavailable source identity, and build timestamp zero. Only a missing resource permits placeholders. Invalid JSON, duplicate keys, nonfinite numbers, missing fields, unsupported schema versions, or invalid field types fail explicitly. Unknown extra keys are ignored.

## Source identity and artifact events

A source distribution bakes the original source identity. Rebuilding it without Git or build environment variables preserves that identity. A conflicting `project.version` fails instead of replacing baked metadata. `SOURCE_DATE_EPOCH` controls the current artifact event when supplied; otherwise the adapter uses the clock. Zero is a valid epoch.

| Runtime fields | Meaning |
| --- | --- |
| `PACKAGE_VERSION`, `BUILD_VERSION` | Static `project.version` |
| `BUILD_GIT_HASH`, `BUILD_GIT_HASH_SHORT` | Full Git commit hash and its first eight characters |
| `BUILD_GIT_BRANCH` | Named branch, or `None` for detached or unavailable Git |
| `BUILD_GIT_DIRTY` | Changes affecting canonical selected source-distribution inputs |
| `BUILD_GIT_COMMIT_TIMESTAMP` | Git committer epoch |
| `SELECTED_SOURCE_DIGEST` | SHA-256 digest of selected input paths and content hashes |
| `SOURCE_TIMESTAMP` | Original source metadata rendering event |
| `SDIST_BUILD_TIMESTAMP` | First source-distribution rendering event, retained downstream |
| `WHEEL_BUILD_TIMESTAMP` | Current wheel rendering event |
| `BUILD_TIMESTAMP`, `BUILD_DATETIME` | Current artifact rendering event and its UTC-naive datetime |

The standard loader also exposes the customizable `VERSION_INFO_SHORT`, `VERSION_INFO`, `VERSION_INFO_LONG`, and `VERSION_INFO_FULL` display strings. Its timestamps describe build events, not installation time. Independently built wheels and source distributions can have different source event times; wheels rebuilt from one source distribution retain that distribution's source time.

A local source tree without committed project metadata or baked provenance can build with unavailable Git fields. Those placeholders do not establish verified publishing identity. This tool does not publish packages or validate publishing eligibility.

## Selected-input dirty state

Both artifact types use canonical source-distribution selection, including inputs such as README files that might not enter a wheel. The adapter requests fresh setuptools manifests for the current source and a HEAD snapshot under the current common build-control configuration. Their union detects selected tracked edits and deletions, plus selected nonignored untracked files. Excluded repository edits and ignored additions do not count.

The committed loader is a real source input: changing a custom display helper changes dirty state and the selected-source digest. Only the configured package's generated provenance sidecar is excluded. Temporary manifest generation uses a fresh egg-info location to avoid stale `SOURCES.txt` caches. Source files, including ignored and untracked inputs, remain untouched; ordinary setuptools build and egg-info caches can still be created.

The initial adapter targets ordinary pure Python setuptools projects. Arbitrary custom setup code, selector plugins, native build hooks, submodules, and Git `export-ignore` attributes need separate validation. The HEAD snapshot copies the current `pyproject.toml`, `MANIFEST.in`, `setup.cfg`, `setup.py`, and root `.gitignore`; it does not discover every possible project-specific configuration dependency. Source selection is not an atomic snapshot against concurrent edits. Selected symlinks escaping the project root and newline filenames fail explicitly. Keep these limits in mind before adopting the adapter for a custom build system.

## Develop and test

The repository follows the nhairs Python package workflow, using development dependency groups and tox with the uv backend:

```sh
uv sync --group dev
uvx tox -e lint
uvx tox
```

The default tox matrix covers CPython 3.11–3.15. GitHub Actions runs it on Ubuntu, macOS, and Windows. Linting validates the project configuration, checks Black formatting at 100 columns, and runs Pylint and Pyrefly.

Tests build actual wheels and source distributions, rebuild outside Git, install distributions into fresh virtual environments, exercise isolated builds with an actual companion wheel, and compare source filesystem inventories. They also cover editable placeholders, strict runtime resource validation, zip imports, shallow and detached Git, selected-input changes, source timestamps, and staged hardlink replacement.

For a targeted local check, run `uvx tox -e py311,py315`. A successful local Linux run does not establish the other operating-system checks; use the GitHub Actions results for those platforms.
