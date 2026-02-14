# PharmaSight RBAC Upgrade – Implementation Plan

## Executive Summary

This document provides a **step-by-step, non-destructive** implementation plan to add branch-aware, fine-grained permissions and role-specific dashboards to PharmaSight – Vyapar-style – **without breaking** the existing user/role system.

---

## 1. Codebase Analysis Summary

### Framework & Architecture
- **Backend**: Python FastAPI
- **Frontend**: Vanilla JavaScript (no React/Vue)
- **Auth**: Supabase Auth (username→email lookup, JWT)
- **Database**: PostgreSQL, SQL migrations in `database/migrations/`
- **Multi-tenant**: Database-per-tenant; tenant resolved via `X-Tenant-Subdomain` header

### Current Schema (Relevant Tables)
| Table | Key Columns | Notes |
|-------|-------------|-------|
| `users` | id, email, username, full_name, phone, is_active, invitation_*, password_set, deleted_at | **No `role` column** – roles via `user_branch_roles` |
| `user_roles` | id, role_name, description | Seeded: Super Admin, admin, pharmacist, cashier, procurement, viewer. **No permissions column** |
| `user_branch_roles` | user_id, branch_id, role_id | **Primary** way users access branches. One user can have multiple branch–role pairs |
| `branches` | id, company_id, name, code | Exists |
| `companies` | id, name, ... | Single company per tenant DB |

### Current Permission Model
- **No `users.role` column** – access is driven by `user_branch_roles`
- Role checks are **frontend-only** (`isAdmin()`, `isPrimaryAdmin()`, `checkIfAdminOrManager()` in `settings.js`, `sales.js`, etc.)
- Backend has **no RBAC middleware** – endpoints do not enforce role/permission
- Dashboard: Today's Sales already supports per-user filter (`user_id` → `batched_by`); other widgets show same data for all
- **Manage Roles** UI exists but `API.users.updateRole` is **not implemented**; role permissions (read/write/admin) are UI placeholders only

### Assumptions
1. **No `users.role`** – we will **not** add a single `role` column; we continue using `user_branch_roles`
2. Existing `user_roles` and `user_branch_roles` remain untouched for structure
3. New tables `permissions` and `role_permissions` are additive
4. Optional `FEATURE_NEW_RBAC` env flag for gradual rollout
5. No Spatie or external RBAC package – manual implementation

---

## 2. Step 1 – Database & Models

### 2.1 Migration: New Tables

**File**: `pharmasight/database/migrations/017_rbac_permissions.sql`

```sql
-- Migration 017: RBAC – Permissions and Role Permissions
-- Non-breaking. Keeps user_roles and user_branch_roles unchanged.

-- Permissions master table
CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    module VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_permissions_module ON permissions(module);
CREATE INDEX IF NOT EXISTS idx_permissions_name ON permissions(name);

-- Role–Permission mapping (branch_id NULL = global for that role)
CREATE TABLE IF NOT EXISTS role_permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_id UUID NOT NULL REFERENCES user_roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    branch_id UUID REFERENCES branches(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Unique: one (role, permission) per branch; for global (branch_id NULL), one per role+permission
CREATE UNIQUE INDEX IF NOT EXISTS idx_role_permissions_unique_global
    ON role_permissions(role_id, permission_id) WHERE branch_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_role_permissions_unique_branch
    ON role_permissions(role_id, permission_id, branch_id) WHERE branch_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_permission ON role_permissions(permission_id);
CREATE INDEX IF NOT EXISTS idx_role_permissions_branch ON role_permissions(branch_id);

-- Optional: default branch for user (for login redirect, etc.)
ALTER TABLE users ADD COLUMN IF NOT EXISTS default_branch_id UUID REFERENCES branches(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_users_default_branch ON users(default_branch_id);

COMMENT ON TABLE permissions IS 'Fine-grained permission definitions (e.g. sales.view_all, reports.view_profit)';
COMMENT ON TABLE role_permissions IS 'Links roles to permissions; branch_id NULL = global, else branch-scoped';
```

**Rollback** (`017_rbac_permissions_down.sql`):

```sql
ALTER TABLE users DROP COLUMN IF EXISTS default_branch_id;
DROP TABLE IF EXISTS role_permissions;
DROP TABLE IF EXISTS permissions;
```

### 2.2 Models

**File**: `pharmasight/backend/app/models/permission.py` (new)

```python
"""
Permission and RolePermission models for RBAC
"""
from sqlalchemy import Column, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP
import uuid
from app.database import Base


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False, unique=True)
    module = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    description = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    role_permissions = relationship("RolePermission", back_populates="permission", cascade="all, delete-orphan")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id = Column(UUID(as_uuid=True), ForeignKey("user_roles.id", ondelete="CASCADE"), nullable=False)
    permission_id = Column(UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False)
    branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    role = relationship("UserRole", back_populates="role_permissions")
    permission = relationship("Permission", back_populates="role_permissions")
    branch = relationship("Branch")
```

Update `pharmasight/backend/app/models/user.py` – add relationship to `UserRole`:

```python
# In UserRole class, add:
from sqlalchemy.orm import relationship  # if not already

role_permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")
```

Update `pharmasight/backend/app/models/__init__.py`:

```python
from .permission import Permission, RolePermission
# Add to __all__: "Permission", "RolePermission"
```

Update `pharmasight/backend/app/models/company.py` – add `default_branch_id` to User if you use a shared User model, or handle in a separate migration. The User model does not currently have `default_branch_id`; add it in `user.py`:

```python
# In User class:
default_branch_id = Column(UUID(as_uuid=True), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True)
```

---

## 3. Step 2 – Permission Seeder

**File**: `pharmasight/database/migrations/018_seed_permissions.sql`

```sql
-- Seed permissions for all modules
INSERT INTO permissions (name, module, action, description) VALUES
-- Sales
('sales.view_own', 'sales', 'view_own', 'View own sales only'),
('sales.view_all', 'sales', 'view_all', 'View all sales'),
('sales.create', 'sales', 'create', 'Create sales invoices'),
('sales.edit', 'sales', 'edit', 'Edit draft invoices'),
('sales.delete', 'sales', 'delete', 'Delete draft invoices'),
('sales.refund', 'sales', 'refund', 'Create credit notes / refunds'),
('sales.batch', 'sales', 'batch', 'Batch invoices and reduce stock'),
-- Reports
('reports.view_sales', 'reports', 'view_sales', 'View sales reports'),
('reports.view_profit', 'reports', 'view_profit', 'View profit / margin reports'),
('reports.view_expenses', 'reports', 'view_expenses', 'View expense reports'),
('reports.view_inventory', 'reports', 'view_inventory', 'View inventory reports'),
('reports.view_unpaid_invoices', 'reports', 'view_unpaid_invoices', 'View unpaid invoices report'),
-- Orders (Order Book, Purchase Orders)
('orders.place', 'orders', 'place', 'Place orders'),
('orders.approve', 'orders', 'approve', 'Approve orders'),
('orders.receive', 'orders', 'receive', 'Receive / GRN'),
-- Purchases
('purchases.view', 'purchases', 'view', 'View purchases'),
('purchases.create', 'purchases', 'create', 'Create GRNs and invoices'),
('purchases.edit', 'purchases', 'edit', 'Edit purchase documents'),
-- Inventory / Stock
('inventory.view', 'inventory', 'view', 'View inventory'),
('inventory.adjust', 'inventory', 'adjust', 'Adjust stock'),
('inventory.stock_take', 'inventory', 'stock_take', 'Participate in stock take'),
-- Payments
('payments.collect', 'payments', 'collect', 'Collect payments'),
('payments.refund', 'payments', 'refund', 'Process refunds'),
('payments.view_reports', 'payments', 'view_reports', 'View payment reports'),
-- Admin
('admin.access_settings', 'admin', 'access_settings', 'Access settings'),
('admin.manage_users', 'admin', 'manage_users', 'Manage users'),
('admin.manage_roles', 'admin', 'manage_roles', 'Manage roles and permissions'),
('admin.manage_company', 'admin', 'manage_company', 'Manage company and branches'),
-- Dashboard (widget-level)
('dashboard.view_own_sales', 'dashboard', 'view_own_sales', 'View own sales widget'),
('dashboard.view_all_sales', 'dashboard', 'view_all_sales', 'View all sales widget'),
('dashboard.view_gross_profit', 'dashboard', 'view_gross_profit', 'View gross profit widget'),
('dashboard.view_expenses', 'dashboard', 'view_expenses', 'View expenses widget'),
('dashboard.view_inventory', 'dashboard', 'view_inventory', 'View inventory widgets'),
('dashboard.view_order_book', 'dashboard', 'view_order_book', 'View order book widget'),
('dashboard.view_unpaid_invoices', 'dashboard', 'view_unpaid_invoices', 'View unpaid invoices widget')
ON CONFLICT (name) DO NOTHING;
```

**File**: `pharmasight/database/migrations/019_map_roles_to_permissions.sql`

```sql
-- Map existing roles to default permission sets
-- Super Admin / admin: all permissions (global)
DO $$
DECLARE
    p RECORD;
    admin_role_id UUID;
BEGIN
    SELECT id INTO admin_role_id FROM user_roles WHERE LOWER(role_name) IN ('super admin', 'admin') LIMIT 1;
    IF admin_role_id IS NOT NULL THEN
        FOR p IN SELECT id FROM permissions LOOP
            INSERT INTO role_permissions (role_id, permission_id, branch_id)
            SELECT admin_role_id, p.id, NULL
            WHERE NOT EXISTS (
                SELECT 1 FROM role_permissions rp
                WHERE rp.role_id = admin_role_id AND rp.permission_id = p.id AND rp.branch_id IS NULL
            );
        END LOOP;
    END IF;
END $$;

-- Pharmacist: sales all, reports, inventory, orders place/receive, payments, no admin
-- Cashier: sales view_own, create, batch, payments collect, dashboard view_own_sales
-- Procurement: orders, purchases, inventory view, dashboard order_book
-- Viewer: read-only (reports view_*, inventory view, dashboard view_*)
-- (Add similar INSERTs for each role – see full script below)
```

**Full role–permission mapping script** (run after 018):

```sql
-- Pharmacist (use WHERE NOT EXISTS to avoid unique violations on re-run)
INSERT INTO role_permissions (role_id, permission_id, branch_id)
SELECT r.id, p.id, NULL
FROM user_roles r
CROSS JOIN permissions p
WHERE LOWER(r.role_name) = 'pharmacist'
AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.branch_id IS NULL)
AND p.name IN (
    'sales.view_all','sales.create','sales.edit','sales.delete','sales.refund','sales.batch',
    'reports.view_sales','reports.view_profit','reports.view_expenses','reports.view_inventory','reports.view_unpaid_invoices',
    'orders.place','orders.approve','orders.receive','purchases.view','purchases.create','purchases.edit',
    'inventory.view','inventory.adjust','inventory.stock_take','payments.collect','payments.refund','payments.view_reports',
    'dashboard.view_all_sales','dashboard.view_gross_profit','dashboard.view_expenses','dashboard.view_inventory','dashboard.view_order_book','dashboard.view_unpaid_invoices'
);

-- Cashier
INSERT INTO role_permissions (role_id, permission_id, branch_id)
SELECT r.id, p.id, NULL
FROM user_roles r
CROSS JOIN permissions p
WHERE LOWER(r.role_name) = 'cashier'
AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.branch_id IS NULL)
AND p.name IN (
    'sales.view_own','sales.create','sales.batch','payments.collect',
    'dashboard.view_own_sales','inventory.view'
);

-- Procurement
INSERT INTO role_permissions (role_id, permission_id, branch_id)
SELECT r.id, p.id, NULL
FROM user_roles r
CROSS JOIN permissions p
WHERE LOWER(r.role_name) = 'procurement'
AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.branch_id IS NULL)
AND p.name IN (
    'orders.place','orders.receive','purchases.view','purchases.create','purchases.edit',
    'inventory.view','dashboard.view_order_book','dashboard.view_inventory'
);

-- Viewer
INSERT INTO role_permissions (role_id, permission_id, branch_id)
SELECT r.id, p.id, NULL
FROM user_roles r
CROSS JOIN permissions p
WHERE LOWER(r.role_name) = 'viewer'
AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id AND rp.branch_id IS NULL)
AND p.name IN (
    'reports.view_sales','reports.view_inventory','inventory.view',
    'dashboard.view_inventory'
);
```

---

## 4. Step 3 – Permission Checker

### 4.1 Helper & Service

**File**: `pharmasight/backend/app/services/permission_service.py` (new)

```python
"""
Permission checking service with caching.
Respects FEATURE_NEW_RBAC – when False, falls back to role-name checks.
"""
import os
from functools import lru_cache
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.user import User, UserRole, UserBranchRole
from app.models.permission import Permission, RolePermission


def _use_new_rbac() -> bool:
    return os.getenv("FEATURE_NEW_RBAC", "true").lower() in ("1", "true", "yes")


def has_permission(
    db: Session,
    user_id: UUID,
    permission_name: str,
    branch_id: Optional[UUID] = None,
) -> bool:
    """
    Check if user has permission (optionally for a branch).
    - If FEATURE_NEW_RBAC=false: fall back to role-based allow (admin/super admin → True).
    - Otherwise: resolve via role_permissions for user's roles at branch (or global).
    """
    if not _use_new_rbac():
        return _legacy_has_permission(db, user_id, permission_name)

    user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not user:
        return False

    # Get user's branch_role pairs (for this branch or any if branch_id is None)
    ubr_q = db.query(UserBranchRole).join(UserRole).filter(UserBranchRole.user_id == user_id)
    if branch_id is not None:
        ubr_q = ubr_q.filter(UserBranchRole.branch_id == branch_id)
    ubrs = ubr_q.all()

    perm = db.query(Permission).filter(Permission.name == permission_name).first()
    if not perm:
        return False

    for ubr in ubrs:
        # Check role_permissions: (role_id, permission_id) with branch_id IN (ubr.branch_id, NULL)
        rp = db.query(RolePermission).filter(
            RolePermission.role_id == ubr.role_id,
            RolePermission.permission_id == perm.id,
            or_(
                RolePermission.branch_id.is_(None),
                RolePermission.branch_id == ubr.branch_id,
            ),
        ).first()
        if rp:
            return True
    return False


def _legacy_has_permission(db: Session, user_id: UUID, permission_name: str) -> bool:
    """Legacy: Super Admin and admin get all; others get minimal."""
    ubrs = db.query(UserBranchRole).join(UserRole).filter(UserBranchRole.user_id == user_id).all()
    for ubr in ubrs:
        rn = (ubr.role.role_name or "").lower()
        if rn in ("super admin", "admin", "administrator"):
            return True
    return False


def get_user_permissions(db: Session, user_id: UUID, branch_id: Optional[UUID] = None) -> set[str]:
    """Return set of permission names for user at branch (or global)."""
    if not _use_new_rbac():
        ubrs = db.query(UserBranchRole).join(UserRole).filter(UserBranchRole.user_id == user_id).all()
        for ubr in ubrs:
            if (ubr.role.role_name or "").lower() in ("super admin", "admin"):
                return {"*"}  # All
        return set()

    ubr_q = db.query(UserBranchRole).join(UserRole).filter(UserBranchRole.user_id == user_id)
    if branch_id is not None:
        ubr_q = ubr_q.filter(UserBranchRole.branch_id == branch_id)
    ubrs = ubr_q.all()

    names = set()
    for ubr in ubrs:
        rps = db.query(Permission.name).join(RolePermission).filter(
            RolePermission.role_id == ubr.role_id,
            or_(
                RolePermission.branch_id.is_(None),
                RolePermission.branch_id == ubr.branch_id,
            ),
        ).all()
        names.update(p.name for p in rps)
    return names
```

### 4.2 Caching (Optional)

Cache per user_id + branch_id in memory (e.g. TTL 60s) or Redis. Example in-memory:

```python
from cachetools import TTLCache
_user_perm_cache: TTLCache = TTLCache(maxsize=500, ttl=60)

def has_permission_cached(db: Session, user_id: UUID, permission_name: str, branch_id: Optional[UUID] = None) -> bool:
    key = (str(user_id), permission_name, str(branch_id) if branch_id else "")
    if key in _user_perm_cache:
        return _user_perm_cache[key]
    v = has_permission(db, user_id, permission_name, branch_id)
    _user_perm_cache[key] = v
    return v
```

### 4.3 Dependency: Current User

**File**: `pharmasight/backend/app/dependencies.py` – add:

```python
def get_current_user_id(request: Request) -> Optional[UUID]:
    """Resolve user_id from X-User-Id header (set by frontend after Supabase auth)."""
    raw = request.headers.get("X-User-Id")
    if not raw:
        return None
    try:
        return UUID(str(raw).strip())
    except (ValueError, TypeError):
        return None
```

Frontend must send `X-User-Id: {user.id}` on API requests. (Confirm your current API client and Supabase flow – you may already pass user context.)

### 4.4 Dual-Check Pattern

In any endpoint that needs a permission:

```python
from app.dependencies import get_tenant_db, get_current_user_id
from app.services.permission_service import has_permission

@router.get("/some-endpoint")
def some_endpoint(
    request: Request,
    db: Session = Depends(get_tenant_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(401, "Unauthorized")
    if not has_permission(db, user_id, "reports.view_profit", branch_id=None):
        raise HTTPException(403, "Forbidden")
    # ...
```

---

## 5. Step 4 – Dashboard Refactor

### 5.1 Current Dashboard Structure

- **File**: `pharmasight/frontend/js/pages/dashboard.js`
- **Widgets**: Total Items in Stock, Total Stock (units), Stock Value, Today's Sales, Expiring Soon
- **Data sources**: `API.inventory.*`, `API.sales.getTodaySummary(branchId, userId)`

### 5.2 Backend: Permission-Aware Endpoints

Add a `GET /api/me/permissions?branch_id=` endpoint:

```python
# In users router or new me.py
@router.get("/me/permissions", response_model=List[str])
def get_my_permissions(
    branch_id: Optional[UUID] = Query(None),
    request: Request = None,
    db: Session = Depends(get_tenant_db),
):
    user_id = get_current_user_id(request)
    if not user_id:
        raise HTTPException(401, "Unauthorized")
    perms = get_user_permissions(db, user_id, branch_id)
    return list(perms)
```

Frontend calls this on load and caches results.

### 5.3 Dashboard Widget Visibility

**File**: `pharmasight/frontend/js/pages/dashboard.js`

1. On load, fetch `GET /api/me/permissions?branch_id={branchId}`.
2. For each widget, check permission before rendering and before fetching data:
   - **Today's Sales**: `dashboard.view_own_sales` → pass `userId`; `dashboard.view_all_sales` → pass `null` (all)
   - **Stock Value, Total Stock, Expiring Soon**: `dashboard.view_inventory`
   - **Gross Profit** (new): `dashboard.view_gross_profit`
   - **Expenses** (new): `dashboard.view_expenses`
   - **Order Book** (new): `dashboard.view_order_book`
   - **Unpaid Invoices** (new): `dashboard.view_unpaid_invoices`

3. Hide widgets the user cannot see (or show placeholder).

Example:

```javascript
const permissions = await API.users.getMyPermissions(BranchContext.getBranch()?.id);
const canViewOwnSales = permissions.includes('dashboard.view_own_sales') || permissions.includes('*');
const canViewAllSales = permissions.includes('dashboard.view_all_sales') || permissions.includes('*');
const canViewInventory = permissions.includes('dashboard.view_inventory') || permissions.includes('*');

if (canViewAllSales || canViewOwnSales) {
    const userId = canViewAllSales ? null : CONFIG.USER_ID;
    const summary = await API.sales.getTodaySummary(branchId, userId);
    // ...
}
if (canViewInventory) {
    // Load stock value, expiring, etc.
}
```

### 5.4 Role-Specific Widget Examples

| Role       | Widgets Shown                                                                 |
|-----------|---------------------------------------------------------------------------------|
| Manager   | Total Sales, Gross Profit, Expenses, Stock Value, Expiring, Order Book         |
| Sales     | Own Sales, Stock (view only)                                                   |
| Procurement | Order Book, Inventory, Pending Deliveries                                    |
| Accountant | Unpaid Invoices, Payments                                                     |

---

## 6. Step 5 – UI Overhaul (Manage Roles)

### 6.1 Location

- **Path**: Settings → Users & Roles → Manage Roles (`renderRolesList`) → Edit Role (`renderEditRoleForm`)
- **File**: `pharmasight/frontend/js/pages/settings.js`

### 6.2 Backend: Roles + Permissions API

**Add endpoints** in `pharmasight/backend/app/api/users.py`:

```python
@router.get("/users/roles/{role_id}/permissions", response_model=List[dict])
def get_role_permissions(role_id: UUID, db: Session = Depends(get_tenant_db)):
    rps = db.query(RolePermission, Permission).join(
        Permission, RolePermission.permission_id == Permission.id
    ).filter(RolePermission.role_id == role_id).all()
    return [
        {"permission_id": str(rp.permission_id), "permission_name": p.name, "branch_id": str(rp.branch_id) if rp.branch_id else None}
        for rp, p in rps
    ]

@router.put("/users/roles/{role_id}/permissions", response_model=dict)
def update_role_permissions(
    role_id: UUID,
    payload: dict,  # {"permissions": [{"permission_name": "sales.view_all", "branch_id": null}], ...}
    db: Session = Depends(get_tenant_db),
):
    role = db.query(UserRole).filter(UserRole.id == role_id).first()
    if not role:
        raise HTTPException(404, "Role not found")
    perms = payload.get("permissions", [])
    db.query(RolePermission).filter(RolePermission.role_id == role_id).delete()
    for p in perms:
        perm = db.query(Permission).filter(Permission.name == p["permission_name"]).first()
        if perm:
            rp = RolePermission(role_id=role_id, permission_id=perm.id, branch_id=p.get("branch_id"))
            db.add(rp)
    db.commit()
    return {"success": True}
```

**Add** `GET /api/permissions` (list all permissions grouped by module):

```python
@router.get("/permissions", response_model=List[dict])
def list_permissions(db: Session = Depends(get_tenant_db)):
    perms = db.query(Permission).order_by(Permission.module, Permission.action).all()
    by_module = {}
    for p in perms:
        if p.module not in by_module:
            by_module[p.module] = []
        by_module[p.module].append({"id": str(p.id), "name": p.name, "action": p.action, "description": p.description})
    return [{"module": m, "permissions": arr} for m, arr in sorted(by_module.items())]
```

### 6.3 Frontend: Vyapar-Style Permission Matrix

Replace `renderEditRoleForm` with:

- **Layout**: Rows = modules (Sales, Reports, Orders, …), Columns = actions (view_own, view_all, create, …)
- **Checkboxes** per (module, action) – checked if `role_permissions` contains that permission
- **Save** → `PUT /api/users/roles/{roleId}/permissions` with `{ permissions: [{ permission_name, branch_id }] }`

Example structure:

```html
<table>
  <thead><tr><th>Module</th><th>View Own</th><th>View All</th><th>Create</th><th>Edit</th><th>Delete</th></tr></thead>
  <tbody>
    <tr><td>Sales</td>
      <td><input type="checkbox" data-permission="sales.view_own" /></td>
      <td><input type="checkbox" data-permission="sales.view_all" /></td>
      ...
    </tr>
    ...
  </tbody>
</table>
<button onclick="saveRolePermissions()">Save Permissions</button>
```

Keep `role_name` and `description` editable; permissions live in the new matrix.

### 6.4 Backward Compatibility

- Old `renderEditRoleForm` sent `permissions: { read, write, admin }` – backend never stored it.
- New UI reads/writes `role_permissions` only.
- Controllers still accept old format if needed; new format takes precedence.

---

## 7. Step 6 – User Assignment Enhancements

### 7.1 Current State

- **Edit User**: Single role dropdown, single branch dropdown
- **Create User**: Same
- **Backend**: `assign_role` assigns one (role, branch) at a time

### 7.2 Enhancements

1. **Multiple branches**: Replace branch dropdown with multi-select (checkboxes or tag input).
2. **Multiple roles per branch**: Allow (branch, [roles]) or multiple (branch, role) rows.
3. **API**:
   - `PUT /api/users/{user_id}/branch-roles` with body: `[{ branch_id, role_ids: [uuid] }]`
   - Replaces all `user_branch_roles` for that user with the new set.

### 7.3 Frontend Form Example

```html
<div class="form-group">
  <label>Branches</label>
  <div>
    ${branches.map(b => `
      <label><input type="checkbox" name="branch_ids" value="${b.id}" ${selectedBranches.includes(b.id) ? 'checked' : ''} />
      ${escapeHtml(b.name)}</label>
    `).join('')}
  </div>
</div>
<div class="form-group">
  <label>Roles per branch</label>
  <!-- For each selected branch, show multi-select of roles -->
</div>
```

---

## 8. Step 7 – Safe Rollout

### 8.1 Feature Flag

- **Env**: `FEATURE_NEW_RBAC=true|false`
- **Behavior**: When `false`, `has_permission` uses `_legacy_has_permission` (admin/super admin → all).
- **Default**: `true` after migration.

### 8.2 Rollback Plan

| Step       | Rollback Action                                                                 |
|------------|----------------------------------------------------------------------------------|
| Migration 017 | Run `017_rbac_permissions_down.sql` (drops new tables, removes `default_branch_id`) |
| Migration 018/019 | No down migration needed; permissions data can stay or be dropped manually |
| Backend code | Revert `permission_service.py`, remove new endpoints, remove permission checks |
| Frontend   | Revert dashboard and settings.js changes; restore old role edit UI              |

### 8.3 Testing Checklist

- [ ] Admin sees all dashboard widgets and Manage Roles matrix
- [ ] Cashier sees only own sales, no profit/expense widgets
- [ ] Procurement sees order book and inventory
- [ ] Toggle `FEATURE_NEW_RBAC=false` → legacy behavior (admin gets all)
- [ ] Edit role, change permissions, save → reflected on next load
- [ ] Assign user to multiple branches + roles → access correct

---

## 9. File Change Summary

| File | Action |
|------|--------|
| `database/migrations/017_rbac_permissions.sql` | Create |
| `database/migrations/017_rbac_permissions_down.sql` | Create |
| `database/migrations/018_seed_permissions.sql` | Create |
| `database/migrations/019_map_roles_to_permissions.sql` | Create |
| `backend/app/models/permission.py` | Create |
| `backend/app/models/user.py` | Add `role_permissions` to UserRole, `default_branch_id` to User |
| `backend/app/models/__init__.py` | Export Permission, RolePermission |
| `backend/app/services/permission_service.py` | Create |
| `backend/app/dependencies.py` | Add `get_current_user_id` |
| `backend/app/api/users.py` | Add `/me/permissions`, `/users/roles/{id}/permissions`, `GET/PUT`; `GET /permissions` |
| `frontend/js/api.js` | Add `users.getMyPermissions`, `users.getRolePermissions`, `users.updateRolePermissions`, `permissions.list` |
| `frontend/js/pages/dashboard.js` | Fetch permissions; conditionally load/render widgets |
| `frontend/js/pages/settings.js` | Replace Edit Role form with permission matrix; enhance user form (multi-branch, multi-role) |

---

## 10. Success Criteria (Recap)

- [ ] Different users see different dashboards based on permissions
- [ ] Manage Roles shows a permission matrix (modules × actions)
- [ ] Toggling permissions and saving persists to `role_permissions`
- [ ] Users can be assigned to multiple branches and multiple roles
- [ ] Existing users and `user_branch_roles` continue to work
- [ ] Old role names remain in DB; new system is additive

---

*End of RBAC Upgrade Implementation Plan*
