"""Tests for project permission bits and legacy role conversion."""

import pytest

from freesearch.models.project_permissions import (
    ADMIN_ACTIONS,
    BASE_ACTIONS,
    DEVELOPER_BITS,
    FULL_DEVELOPER,
    PERMISSION_CATALOG,
    PROVIDER_OWNER_BIT,
    READ_ONLY,
    STANDARD,
    decode_bits,
    effective_project_permissions,
    legacy_roles_to_bits,
    validate_permission_bits,
)


@pytest.mark.parametrize(
    ("bit", "key", "action"),
    [
        (1, "search", "search.execute"),
        (2, "fetch", "fetch.execute"),
        (4, "traces", "traces.read"),
        (8, "usage", "usage.read"),
        (16, "settings_write", "settings.write"),
        (32, "settings_copy", "settings.copy"),
        (64, "providers_configure", "providers.configure"),
        (128, "tokens", "tokens.manage"),
    ],
)
def test_each_developer_bit(bit: int, key: str, action: str) -> None:
    assert decode_bits(bit) == {key}
    assert effective_project_permissions(["project_member"], bit) == BASE_ACTIONS | {action}


def test_provider_owner_is_admin_only() -> None:
    assert decode_bits(PROVIDER_OWNER_BIT) == {"provider_owner"}
    assert "providers.supply" not in effective_project_permissions(
        ["project_member"], PROVIDER_OWNER_BIT
    )
    assert "providers.supply" in effective_project_permissions(
        ["project_admin"], PROVIDER_OWNER_BIT
    )


@pytest.mark.parametrize(
    ("preset", "keys"),
    [
        (READ_ONLY, {"traces", "usage"}),
        (STANDARD, {"search", "fetch", "traces", "usage"}),
        (FULL_DEVELOPER, {item.key for item in PERMISSION_CATALOG if item.developer_toggle}),
    ],
)
def test_presets(preset: int, keys: set[str]) -> None:
    assert decode_bits(preset) == keys


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ([], 0),
        (["project_admin"], 0),
        (["project_member"], STANDARD),
        (["routing_editor"], 0),
        (["provider_editor"], 64),
        (["token_manager"], 128),
        (["provider_editor", "token_manager"], 192),
        (["project_member", "provider_editor"], 79),
        (["project_member", "routing_editor", "provider_editor", "token_manager"], 207),
        (["project_admin", "provider_editor", "token_manager"], 192),
    ],
)
def test_legacy_role_mapping(roles: list[str], expected: int) -> None:
    assert legacy_roles_to_bits(roles) == expected


def test_admin_has_all_developer_and_admin_actions_without_owner() -> None:
    developer_actions = {item.action for item in PERMISSION_CATALOG if item.developer_toggle}
    assert effective_project_permissions(["project_admin"], 0) == (
        BASE_ACTIONS | ADMIN_ACTIONS | developer_actions
    )
    assert decode_bits(DEVELOPER_BITS) == {
        item.key for item in PERMISSION_CATALOG if item.developer_toggle
    }


@pytest.mark.parametrize("bits", [-1, 256, 16384, 65536, 32768 | 256])
def test_reserved_bits_are_rejected(bits: int) -> None:
    with pytest.raises(ValueError, match="reserved bits"):
        validate_permission_bits(bits)
    with pytest.raises(ValueError, match="reserved bits"):
        decode_bits(bits)
    with pytest.raises(ValueError, match="reserved bits"):
        effective_project_permissions(["project_admin"], bits)
