# User Permissions Management Guide

## Overview

PharmaSight now includes a comprehensive permission system that allows company administrators to control what users can see and do in the application. Permissions are managed through roles, and each user inherits permissions from their assigned roles.

## Key Features

1. **Role-Based Permissions**: Permissions are assigned to roles, not individual users
2. **Dashboard Card Visibility**: Control which dashboard cards users can see
3. **Data Access Control**: Control whether users see all data or only their own (e.g., sales)
4. **Field-Level Permissions**: Control visibility of sensitive fields like unit costs
5. **Permission Matrix UI**: Easy-to-use interface for managing role permissions

## How to Set Up Permissions

### Step 1: Access User Management

1. Navigate to **Settings** → **Users & Roles**
2. Click **"Manage Roles"** to view all roles

### Step 2: Edit Role Permissions

1. Click **"Edit"** next to the role you want to configure
2. You'll see a permissions matrix showing all available permissions grouped by module
3. Check/uncheck permissions to grant or revoke access
4. Click **"Save Role"** to apply changes

### Step 3: Assign Roles to Users

1. In **Settings** → **Users & Roles**, click **"Edit"** next to a user
2. Select the appropriate role from the dropdown
3. Assign the user to a branch (if needed)
4. Click **"Update User"**

### Step 4: View User Permissions

When editing a user, scroll down to see the **"User Permissions"** section. This shows all permissions the user has inherited from their role(s).

## Permission Categories

### Dashboard Permissions

- `dashboard.view_items` - View items count card
- `dashboard.view_inventory` - View inventory cards
- `dashboard.view_stock_value` - View stock value card
- `dashboard.view_sales` - View sales card
- `dashboard.view_expiring` - View expiring items card
- `dashboard.view_order_book` - View order book card

### Sales Permissions

- `sales.view_own` - View only sales created by the user
- `sales.view_all` - View all sales (includes view_own)
- `sales.create` - Create sales invoices
- `sales.edit` - Edit draft invoices
- `sales.delete` - Delete draft invoices
- `sales.sell_below_min_margin` - Allow selling below minimum margin

### Inventory Permissions

- `inventory.view` - View inventory and stock
- `inventory.view_cost` - View unit cost and purchase prices
- `inventory.create` - Add stock (receiving)
- `inventory.edit` - Adjust stock
- `inventory.delete` - Write-off stock

### Items Permissions

- `items.view` - View items
- `items.view_cost` - View item unit cost and purchase prices

## Common Permission Scenarios

### Scenario 1: Sales Person Sees Only Their Sales

1. Create or edit a role (e.g., "Sales Person")
2. Grant `sales.view_own` permission
3. Grant `sales.create` permission
4. Grant `dashboard.view_sales` permission
5. Assign users to this role

**Result**: Users with this role will only see their own sales in the dashboard and sales reports.

### Scenario 2: Manager Sees All Sales

1. Create or edit a role (e.g., "Manager")
2. Grant `sales.view_all` permission (this includes view_own)
3. Grant `dashboard.view_sales` permission
4. Assign managers to this role

**Result**: Managers will see all sales across all users.

### Scenario 3: Hide Unit Cost from Sales Staff

1. Edit the "Sales Person" role
2. **Do NOT** grant `items.view_cost` or `inventory.view_cost` permissions
3. Save the role

**Result**: Sales staff will not see unit costs or purchase prices in the UI.

### Scenario 4: Auditor Cannot See Information Cards

1. Create or edit an "Auditor" role
2. Grant only report-viewing permissions
3. **Do NOT** grant `dashboard.view_items`, `dashboard.view_inventory`, etc.
4. Assign auditors to this role

**Result**: Auditors will see a minimal dashboard without information cards.

### Scenario 5: Admin Sees Everything

1. Use the "Super Admin" or "admin" role
2. This role should have all permissions by default
3. Assign administrators to this role

**Result**: Admins see all cards, all data, and all fields.

## Technical Implementation

### Frontend Permission Checking

The frontend uses `window.Permissions` utility functions:

```javascript
// Check if user has a permission
const canView = await window.Permissions.hasPermission('sales.view_all', branchId);

// Check if user can view a dashboard card
const canViewCard = await window.Permissions.canViewDashboardCard('todaySales', branchId);

// Check if user can view unit costs
const canViewCost = await window.Permissions.canViewUnitCost(branchId);

// Get sales view permissions
const salesPerms = await window.Permissions.getSalesViewPermissions(branchId);
// Returns: { canViewAll: boolean, canViewOwn: boolean }
```

### Backend Permission Checking

The backend provides an endpoint to get user permissions:

```
GET /api/users/{user_id}/permissions?branch_id={branch_id}
```

Returns:
```json
{
  "permissions": ["sales.view_all", "dashboard.view_sales", ...]
}
```

## Best Practices

1. **Start with Roles**: Create roles first, then assign permissions to roles
2. **Least Privilege**: Grant only the minimum permissions needed for each role
3. **Test Permissions**: After setting up permissions, test with a test user account
4. **Document Roles**: Use role descriptions to document what each role is for
5. **Regular Audits**: Periodically review user roles and permissions

## Troubleshooting

### User Can't See Dashboard Cards

1. Check if the user has a role assigned
2. Check if the role has the required dashboard permissions
3. Check if the user is assigned to the correct branch

### User Sees All Sales When They Should Only See Their Own

1. Verify the user's role has `sales.view_own` (not `sales.view_all`)
2. Check if the user has multiple roles - permissions are combined
3. Verify the dashboard is checking permissions correctly

### Unit Costs Still Visible

1. Check if the role has `items.view_cost` or `inventory.view_cost`
2. Clear browser cache and reload
3. Check if the user has admin role (admins see everything)

## Migration Notes

If you're upgrading from an older version:

1. Run the database migrations (`017_rbac_permissions.sql` and `018_seed_permissions.sql`)
2. Assign default permissions to existing roles
3. Review and adjust permissions as needed
4. Test with a non-admin user account

## Support

For questions or issues with permissions:
1. Check this guide first
2. Review the role permissions matrix
3. Test with a test user account
4. Contact your system administrator
