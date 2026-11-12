"""Validate JSON provenance; also embedded in the committed runtime loader."""

import json as _json

_FIELDS = (
    "PACKAGE_VERSION",
    "BUILD_VERSION",
    "BUILD_GIT_HASH",
    "BUILD_GIT_HASH_SHORT",
    "BUILD_GIT_BRANCH",
    "BUILD_GIT_DIRTY",
    "BUILD_GIT_COMMIT_TIMESTAMP",
    "SELECTED_SOURCE_DIGEST",
    "SOURCE_TIMESTAMP",
    "BUILD_TIMESTAMP",
    "SDIST_BUILD_TIMESTAMP",
    "WHEEL_BUILD_TIMESTAMP",
)


# Exact JSON types deliberately reject bool masquerading as an integer.
def _validate(data):  # pylint: disable=too-many-branches
    """Validate the complete provenance schema and return the original mapping."""
    if (
        not isinstance(data, dict)
        or (
            not isinstance(data.get("schema_version"), int)
            or isinstance(data.get("schema_version"), bool)
        )
        or data["schema_version"] != 1
    ):
        raise ValueError("unsupported provenance schema; expected schema_version=1")
    if not set(_FIELDS).issubset(data):
        raise ValueError("provenance resource is missing required fields")
    for key in ("PACKAGE_VERSION", "BUILD_VERSION"):
        if not isinstance(data[key], str) or not data[key]:
            raise ValueError(key + " must be a nonempty string")
    if data["PACKAGE_VERSION"] != data["BUILD_VERSION"]:
        raise ValueError("static package and build versions disagree")
    for key in (
        "SOURCE_TIMESTAMP",
        "BUILD_TIMESTAMP",
        "SDIST_BUILD_TIMESTAMP",
        "WHEEL_BUILD_TIMESTAMP",
        "BUILD_GIT_COMMIT_TIMESTAMP",
    ):
        value = data[key]
        if value is None and key not in ("SOURCE_TIMESTAMP", "BUILD_TIMESTAMP"):
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(key + " must be a nonnegative integer or permitted null")
    for key, sizes in (("BUILD_GIT_HASH", (40, 64)), ("SELECTED_SOURCE_DIGEST", (64,))):
        value = data[key]
        if value is not None and (
            not isinstance(value, str)
            or len(value) not in sizes
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("invalid " + key)
    full = data["BUILD_GIT_HASH"]
    if data["BUILD_GIT_HASH_SHORT"] != (full[:8] if full else None):
        raise ValueError("short hash disagrees with full hash")
    if data["BUILD_GIT_BRANCH"] is not None and not isinstance(data["BUILD_GIT_BRANCH"], str):
        raise ValueError("branch must be a string or null")
    if data["BUILD_GIT_DIRTY"] is not None and not isinstance(data["BUILD_GIT_DIRTY"], bool):
        raise ValueError("dirty must be boolean or null")
    return data


def _unique_object(pairs):
    """Build a JSON object while rejecting duplicate keys."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate provenance key: " + key)
        result[key] = value
    return result


def _reject_constant(value):
    """Reject JSON parser extensions for nonfinite numeric values."""
    raise ValueError("invalid JSON constant: " + value)


def _loads(raw):
    """Parse strict JSON and validate its provenance payload."""
    return _validate(
        _json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    )
