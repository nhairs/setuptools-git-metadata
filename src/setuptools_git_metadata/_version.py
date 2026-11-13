"""Load build information for this package or a copy of this module."""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from importlib import resources
import json
from typing import Final, Optional

SCHEMA_VERSION = 1
_METADATA_MISSING = "__metadata_missing__"


@dataclass(frozen=True)
class GitMetadata:  # pylint: disable=too-many-instance-attributes
    """Version and Git information recorded when a distribution was built."""

    # These names preserve the public runtime constant interface.
    # pylint: disable=invalid-name
    schema_version: int = SCHEMA_VERSION
    PACKAGE_VERSION: str = _METADATA_MISSING
    BUILD_VERSION: str = _METADATA_MISSING
    BUILD_GIT_HASH: str = _METADATA_MISSING
    BUILD_GIT_HASH_SHORT: str = _METADATA_MISSING
    BUILD_GIT_BRANCH: Optional[str] = None
    BUILD_GIT_DIRTY: Optional[bool] = None
    BUILD_GIT_COMMIT_TIMESTAMP: Optional[int] = None
    SELECTED_SOURCE_DIGEST: str = _METADATA_MISSING
    SOURCE_TIMESTAMP: int = 0
    BUILD_TIMESTAMP: int = 0
    SDIST_BUILD_TIMESTAMP: Optional[int] = None
    WHEEL_BUILD_TIMESTAMP: Optional[int] = None

    @classmethod
    def from_package(cls, package: str) -> "GitMetadata":
        """Read the package resource, using defaults only when it is absent."""
        try:
            raw = (
                resources.files(package).joinpath("_git_metadata.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return cls()
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("schema_version"), int)
            or isinstance(data.get("schema_version"), bool)
            or data["schema_version"] != SCHEMA_VERSION
        ):
            raise ValueError(
                f"unsupported provenance schema; expected schema_version={SCHEMA_VERSION}"
            )
        model_fields = fields(cls)
        if not {field.name for field in model_fields}.issubset(data):
            raise ValueError("provenance resource is missing required fields")
        values = {
            field.name: (
                _METADATA_MISSING
                if field.type is str and data[field.name] is None
                else data[field.name]
            )
            for field in model_fields
        }
        return cls(**values)

    @property
    def BUILD_DATETIME(self) -> datetime:
        """Return the build time as a UTC-naive datetime."""
        return datetime.fromtimestamp(self.BUILD_TIMESTAMP, timezone.utc).replace(tzinfo=None)

    @property
    def VERSION_INFO_SHORT(self) -> str:
        """Return the declared build version."""
        return self.BUILD_VERSION

    @property
    def VERSION_INFO(self) -> str:
        """Return the build version with its abbreviated commit."""
        return f"{self.BUILD_VERSION}@{self.BUILD_GIT_HASH_SHORT}"

    @property
    def VERSION_INFO_LONG(self) -> str:
        """Return the build version, branch and abbreviated commit."""
        return f"{self.BUILD_VERSION} ({self.BUILD_GIT_BRANCH}@{self.BUILD_GIT_HASH_SHORT})"

    @property
    def VERSION_INFO_FULL(self) -> str:
        """Return the package/build versions, source identity and build time."""
        return (
            f"{self.PACKAGE_VERSION} ({self.BUILD_VERSION})\n"
            f"{self.BUILD_GIT_BRANCH}@{self.BUILD_GIT_HASH}\nBuilt: {self.BUILD_DATETIME}"
        )


# pylint: enable=invalid-name
BUILD_INFO: Final[GitMetadata] = GitMetadata.from_package(__package__)

# Explicit aliases also support existing imports and custom module-level helpers.
PACKAGE_VERSION = BUILD_INFO.PACKAGE_VERSION
BUILD_VERSION = BUILD_INFO.BUILD_VERSION
BUILD_GIT_HASH = BUILD_INFO.BUILD_GIT_HASH
BUILD_GIT_HASH_SHORT = BUILD_INFO.BUILD_GIT_HASH_SHORT
BUILD_GIT_BRANCH = BUILD_INFO.BUILD_GIT_BRANCH
BUILD_GIT_DIRTY = BUILD_INFO.BUILD_GIT_DIRTY
BUILD_GIT_COMMIT_TIMESTAMP = BUILD_INFO.BUILD_GIT_COMMIT_TIMESTAMP
SELECTED_SOURCE_DIGEST = BUILD_INFO.SELECTED_SOURCE_DIGEST
SOURCE_TIMESTAMP = BUILD_INFO.SOURCE_TIMESTAMP
BUILD_TIMESTAMP = BUILD_INFO.BUILD_TIMESTAMP
SDIST_BUILD_TIMESTAMP = BUILD_INFO.SDIST_BUILD_TIMESTAMP
WHEEL_BUILD_TIMESTAMP = BUILD_INFO.WHEEL_BUILD_TIMESTAMP
BUILD_DATETIME = BUILD_INFO.BUILD_DATETIME
VERSION_INFO_SHORT = BUILD_INFO.VERSION_INFO_SHORT
VERSION_INFO = BUILD_INFO.VERSION_INFO
VERSION_INFO_LONG = BUILD_INFO.VERSION_INFO_LONG
VERSION_INFO_FULL = BUILD_INFO.VERSION_INFO_FULL
