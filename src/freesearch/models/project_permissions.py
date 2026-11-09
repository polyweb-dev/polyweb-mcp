"""Pure project permission bits and legacy role conversion."""

from collections.abc import Iterable
from enum import IntFlag
from typing import Final

from pydantic import BaseModel, ConfigDict


class ProjectPermission(IntFlag):
    """Stored project membership permission bits."""

    SEARCH = 1
    FETCH = 2
    TRACES = 4
    USAGE = 8
    SETTINGS_WRITE = 16
    SETTINGS_COPY = 32
    PROVIDERS_CONFIGURE = 64
    TOKENS = 128
    PROVIDER_OWNER = 32768


DEVELOPER_BITS: Final[int] = 255
PROVIDER_OWNER_BIT: Final[int] = int(ProjectPermission.PROVIDER_OWNER)
ALLOWED_BITS: Final[int] = DEVELOPER_BITS | PROVIDER_OWNER_BIT
READ_ONLY: Final[int] = 12
STANDARD: Final[int] = 15
FULL_DEVELOPER: Final[int] = DEVELOPER_BITS


class PermissionDefinition(BaseModel):
    """One catalog entry suitable for presenting a permission switch."""

    model_config = ConfigDict(frozen=True)

    key: str
    bit: int
    action: str
    group: str
    developer_toggle: bool


PERMISSION_CATALOG: Final[tuple[PermissionDefinition, ...]] = (
    PermissionDefinition(
        key="search", bit=1, action="search.execute", group="Requests", developer_toggle=True
    ),
    PermissionDefinition(
        key="fetch", bit=2, action="fetch.execute", group="Requests", developer_toggle=True
    ),
    PermissionDefinition(
        key="traces", bit=4, action="traces.read", group="Insight", developer_toggle=True
    ),
    PermissionDefinition(
        key="usage", bit=8, action="usage.read", group="Insight", developer_toggle=True
    ),
    PermissionDefinition(
        key="settings_write",
        bit=16,
        action="settings.write",
        group="Configuration",
        developer_toggle=True,
    ),
    PermissionDefinition(
        key="settings_copy",
        bit=32,
        action="settings.copy",
        group="Configuration",
        developer_toggle=True,
    ),
    PermissionDefinition(
        key="providers_configure",
        bit=64,
        action="providers.configure",
        group="Configuration",
        developer_toggle=True,
    ),
    PermissionDefinition(
        key="tokens", bit=128, action="tokens.manage", group="API keys", developer_toggle=True
    ),
    PermissionDefinition(
        key="provider_owner",
        bit=32768,
        action="providers.supply",
        group="Ownership",
        developer_toggle=False,
    ),
)

BASE_ACTIONS: Final[frozenset[str]] = frozenset(
    {"project.read", "members.read", "settings.read", "providers.read"}
)
ADMIN_ACTIONS: Final[frozenset[str]] = frozenset(
    {"members.manage", "roles.assign", "project.archive"}
)


def validate_permission_bits(bits: int) -> int:
    """Reject negative or reserved bits at the API boundary."""

    if bits < 0 or bits & ~ALLOWED_BITS:
        raise ValueError("permission mask contains reserved bits")
    return bits


def decode_bits(bits: int) -> frozenset[str]:
    """Return catalog keys represented by a valid permission mask."""

    validate_permission_bits(bits)
    return frozenset(item.key for item in PERMISSION_CATALOG if bits & item.bit)


def legacy_roles_to_bits(role_keys: Iterable[str]) -> int:
    """Fold old project roles into the stored developer permission mask."""

    bits = 0
    for role in role_keys:
        if role == "project_member":
            bits |= STANDARD
        elif role == "provider_editor":
            bits |= int(ProjectPermission.PROVIDERS_CONFIGURE)
        elif role == "token_manager":
            bits |= int(ProjectPermission.TOKENS)
    return bits


def effective_project_permissions(role_keys: Iterable[str], bits: int) -> frozenset[str]:
    """Resolve a member's actions; provider ownership requires an admin role."""

    validate_permission_bits(bits)
    is_admin = "project_admin" in role_keys
    actions = set(BASE_ACTIONS)
    actions.update(
        item.action
        for item in PERMISSION_CATALOG
        if item.developer_toggle and (is_admin or bits & item.bit)
    )
    if is_admin:
        actions.update(ADMIN_ACTIONS)
        if bits & PROVIDER_OWNER_BIT:
            actions.add("providers.supply")
    return frozenset(actions)
