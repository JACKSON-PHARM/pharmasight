"""
Permission constants for RBAC.
HQ-only permissions: only available when user is at the HQ branch.
"""
# Permissions that require the user to be at the HQ (headquarters) branch
# Non-HQ branches cannot perform these actions even if the role grants them
HQ_ONLY_PERMISSIONS = frozenset({
    "items.create",
    "suppliers.create",
    "users.create",
    "users.edit",  # includes create user, activate/deactivate
    "settings.create",  # create branches
    "orders.create",  # place orders (order book - external ordering)
    "purchases.create",  # create GRNs/purchase orders from external suppliers
})
