"""Load build information for this package or a copy of this module."""

import dataclasses
import datetime
import importlib.resources
import json
import typing

_SCHEMA_VERSION = 1
_METADATA_MISSING = "__metadata_missing__"

__all__ = ["GitMetadata", "BUILD_INFO"]


@dataclasses.dataclass(frozen=True)
class GitMetadata:  # pylint: disable=too-many-instance-attributes
    """Version and Git information recorded when a distribution was built."""

    # Frozen fields and properties use the constant names exposed by BUILD_INFO.
    # pylint: disable=invalid-name
    _schema_version: typing.ClassVar[int] = _SCHEMA_VERSION
    PACKAGE_VERSION: str = _METADATA_MISSING
    BUILD_VERSION: str = _METADATA_MISSING
    BUILD_GIT_HASH: str = _METADATA_MISSING
    BUILD_GIT_HASH_SHORT: str = _METADATA_MISSING
    BUILD_GIT_BRANCH: typing.Optional[str] = None
    BUILD_GIT_DIRTY: typing.Optional[bool] = None
    BUILD_GIT_COMMIT_TIMESTAMP: typing.Optional[int] = None
    SELECTED_SOURCE_DIGEST: str = _METADATA_MISSING
    SOURCE_TIMESTAMP: int = 0
    BUILD_TIMESTAMP: int = 0
    SDIST_BUILD_TIMESTAMP: typing.Optional[int] = None
    WHEEL_BUILD_TIMESTAMP: typing.Optional[int] = None

    @classmethod
    # Once the copied runtime requires Python 3.11+, use typing.Self here.
    def from_package(cls, package: str) -> "GitMetadata":
        """Read the package resource, using defaults only when it is absent."""
        try:
            raw = (
                importlib.resources.files(package)
                .joinpath("_git_metadata.json")
                .read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return cls()
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("schema_version"), int)
            # bool subclasses int, so True must be rejected explicitly.
            or isinstance(data.get("schema_version"), bool)
            or data["schema_version"] != _SCHEMA_VERSION
        ):
            raise ValueError(
                f"unsupported metadata schema; expected schema_version={_SCHEMA_VERSION}"
            )
        model_fields = dataclasses.fields(cls)
        if not {field.name for field in model_fields}.issubset(data):
            raise ValueError("metadata is missing required fields")
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
    def BUILD_DATETIME(self) -> datetime.datetime:
        """Return the build time as a UTC-naive datetime."""
        return datetime.datetime.fromtimestamp(self.BUILD_TIMESTAMP, datetime.timezone.utc).replace(
            tzinfo=None
        )

    @property
    def VERSION_INFO_SHORT(self) -> str:
        """Brief text for compact displays. Edit this single-line template for your needs."""
        return self.BUILD_VERSION

    @property
    def VERSION_INFO(self) -> str:
        """Text for routine output. Edit this single-line template for your needs."""
        return f"{self.BUILD_VERSION}@{self.BUILD_GIT_HASH_SHORT}"

    @property
    def VERSION_INFO_LONG(self) -> str:
        """Expanded text for diagnostics. Edit this single-line template for your needs."""
        return f"{self.BUILD_VERSION} ({self.BUILD_GIT_BRANCH}@{self.BUILD_GIT_HASH_SHORT})"

    @property
    def VERSION_INFO_FULL(self) -> str:
        """Detailed text for reports. Edit this multi-line template for your needs."""
        return (
            f"{self.PACKAGE_VERSION} ({self.BUILD_VERSION})\n"
            f"{self.BUILD_GIT_BRANCH}@{self.BUILD_GIT_HASH}\nBuilt: {self.BUILD_DATETIME}"
        )


# pylint: enable=invalid-name
BUILD_INFO: typing.Final[GitMetadata] = GitMetadata.from_package(__package__)
