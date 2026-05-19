"""Canonical role keys and permission templates."""
from app.role_catalog import (
    is_assignable_role,
    normalize_role_key,
    permission_names_for_admin,
    template_permission_names,
)


def test_normalize_super_admin_aliases():
    assert normalize_role_key("Super Admin") == "super_admin"
    assert normalize_role_key("super admin") == "super_admin"
    assert normalize_role_key("super_admin") == "super_admin"


def test_platform_super_admin_not_assignable():
    assert is_assignable_role("platform_super_admin") is False
    assert is_assignable_role("super_admin") is True


def test_admin_template_excludes_create():
    all_names = [
        "modules.pharmacy",
        "sales.view",
        "sales.create",
        "sales.edit",
        "inventory.delete",
    ]
    names = permission_names_for_admin(all_names)
    assert "modules.pharmacy" in names
    assert "sales.view" in names
    assert "sales.create" not in names
    assert "sales.edit" in names


def test_template_for_pharmacist():
    all_names = ["modules.lab", "sales.view", "sales.create", "finance.view"]
    names = template_permission_names("pharmacist", all_names)
    assert names is not None
    assert "modules.pharmacy" in names
    assert "sales.view" in names
    assert "modules.lab" not in names
