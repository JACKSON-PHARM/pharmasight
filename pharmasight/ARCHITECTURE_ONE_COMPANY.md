# PharmaSight Architecture: ONE COMPANY = ONE DATABASE

## 🏛️ Architectural Decision

**This database represents exactly ONE COMPANY. There is no multi-company tenancy.**

## 📋 Authoritative Rules

1. **ONE COMPANY PER DATABASE**: This database represents exactly one company.
2. **All users belong implicitly to this company**: No company_id needed in users table.
3. **Users have NO company-level roles**: Roles are assigned ONLY per branch.
4. **Branch-level access only**: Users can only access branches they are explicitly assigned to via `user_branch_roles`.
5. **Items are company-level**: Items are created at company level and shared across all branches.
6. **Pricing is GLOBAL per company**: No branch-level price overrides allowed.
7. **Inventory, sales, purchases, invoices are BRANCH-SPECIFIC**: All transactions are tied to a specific branch.
8. **Invoice numbers MUST include branch code**: Format `{BRANCH_CODE}-INV-YYYY-000001`.
9. **Database is single source of truth**: Backend enforces access rules.
10. **Branch code is REQUIRED**: Cannot create a branch without a code.

## 🗄️ Database Schema Changes

### New Tables

1. **`users`**: Application users table
   - `id` (UUID, primary key, matches Supabase Auth user_id)
   - `email`, `full_name`, `phone`, `is_active`
   - No `company_id` - all users belong to the single company

2. **`user_roles`**: System role definitions
   - Pre-seeded roles: admin, pharmacist, cashier, procurement, viewer

3. **`user_branch_roles`**: **THE ONLY WAY** users access branches
   - Links user → branch → role
   - No company-level roles exist

### Updated Tables

1. **`companies`**: 
   - Database trigger enforces ONE COMPANY rule
   - Comment: "ONE COMPANY PER DATABASE"

2. **`branches`**: 
   - `code` is now REQUIRED (NOT NULL)
   - Used in invoice numbering
   - Unique constraint: (company_id, code)

3. **`document_sequences`**: 
   - Branch-specific sequences
   - Prefix includes branch code
   - Format: `{BRANCH_CODE}-INV-YYYY-000001`

### Database Functions

1. **`get_next_document_number()`**: 
   - **ENFORCES** branch code in invoice numbers
   - Raises error if branch code is missing
   - Format: `{BRANCH_CODE}-{TYPE}-YYYY-000001`

2. **`get_company_id()`**: 
   - Helper function to get the single company ID
   - Returns UUID of the one company in this database

3. **`enforce_single_company()`**: 
   - Trigger function that prevents multiple companies
   - Raises error on attempt to insert second company

## 🚀 Startup Flow

### Endpoint: `POST /api/startup`

Complete initialization in one call:

```json
{
  "company": {
    "name": "PharmaSight Meds Ltd",
    "registration_number": "PVT-JZUA3728",
    "pin": "P05248438Q",
    "phone": "0708476318",
    "email": "pharmasightsolutions@gmail.com",
    "address": "5M35+849",
    "currency": "KES",
    "timezone": "Africa/Nairobi",
    "fiscal_start_date": "2026-10-01"
  },
  "admin_user": {
    "id": "uuid-from-supabase-auth",
    "email": "admin@pharmasight.com",
    "full_name": "Admin User",
    "phone": "0700000000"
  },
  "branch": {
    "name": "PharmaSight Main Branch",
    "code": "MAIN",
    "address": "5M35+849",
    "phone": "0708476318"
  }
}
```

**What it does:**
1. ✅ Creates company (enforces ONE COMPANY)
2. ✅ Creates admin user (must match Supabase Auth user_id)
3. ✅ Creates first branch (code is REQUIRED)
4. ✅ Assigns admin role to branch
5. ✅ Initializes document sequences (with branch code)
6. ✅ Initializes pricing defaults

### Check Status: `GET /api/startup/status`

Returns:
```json
{
  "initialized": true,
  "company_id": "uuid-of-company"
}
```

## 🔐 Access Control

### Branch-Level Access Only

- Users can ONLY access branches they are assigned to via `user_branch_roles`
- No company-level permissions exist
- All API endpoints must check: `user_branch_roles` → `branch_id` → `role_id`

### Example Access Check

```python
# Check if user has access to branch
def check_branch_access(db: Session, user_id: UUID, branch_id: UUID, required_role: str = None):
    query = db.query(UserBranchRole).filter(
        UserBranchRole.user_id == user_id,
        UserBranchRole.branch_id == branch_id
    )
    if required_role:
        query = query.join(UserRole).filter(UserRole.role_name == required_role)
    return query.first() is not None
```

## 📝 Invoice Numbering

### Format

- **Sales Invoice**: `{BRANCH_CODE}-INV-YYYY-000001`
- **GRN**: `{BRANCH_CODE}-GRN-YYYY-000001`
- **Credit Note**: `{BRANCH_CODE}-CN-YYYY-000001`
- **Payment**: `{BRANCH_CODE}-PAY-YYYY-000001`

### Enforcement

- Database function `get_next_document_number()` **REQUIRES** branch code
- Raises exception if branch code is NULL or empty
- Branch code is automatically included in prefix

## 🔄 Migration Steps

### For Existing Databases

1. **Run schema**: `database/schema.sql`
2. **Migrate existing data** (if any):
   - Ensure all branches have codes
   - Create users table entries from Supabase Auth
   - Assign users to branches via `user_branch_roles`
3. **Verify single company**: Check that only ONE company exists

### For New Databases

1. Run `schema.sql` to create all tables
2. Use `/api/startup` endpoint for initialization
3. Done!

## ⚠️ Breaking Changes

1. **Branch code is now REQUIRED**: Cannot create branch without code
2. **Single company only**: Cannot create multiple companies (database trigger enforces)
3. **Users table required**: Must have users table (not just Supabase Auth)
4. **Access control changed**: All access is branch-level, no company-level roles
5. **Invoice number format**: Now includes branch code and year

## 📚 Files Changed

### Database
- `database/schema.sql` - Authoritative schema with ONE COMPANY architecture

### Backend Models
- `backend/app/models/user.py` - New: User, UserRole, UserBranchRole models
- `backend/app/models/settings.py` - New: DocumentSequence model
- `backend/app/models/company.py` - Updated: Branch.code is now required

### Backend Services
- `backend/app/services/startup_service.py` - New: Complete initialization service
- `backend/app/services/document_service.py` - Updated: Uses database function that enforces branch codes

### Backend API
- `backend/app/api/startup.py` - New: `/api/startup` endpoint
- `backend/app/api/company.py` - Updated: Enforces single company, requires branch code

### Backend Schemas
- `backend/app/schemas/startup.py` - New: Startup request/response schemas
- `backend/app/schemas/company.py` - Updated: Branch.code is required

### Backend Main
- `backend/app/main.py` - Updated: Includes startup router

## ✅ Verification Checklist

- [ ] Database schema updated with users table
- [ ] Single company trigger created
- [ ] Branch code is required (NOT NULL)
- [ ] Document numbering function enforces branch code
- [ ] Startup endpoint works
- [ ] Company creation enforces single company
- [ ] Branch creation requires code
- [ ] Invoice numbers include branch code
- [ ] All users belong to single company (no company_id in users)
- [ ] All access is branch-level only

## 🎯 Next Steps (TODO)

1. ✅ Database schema aligned
2. ✅ Startup service created
3. ✅ Document numbering updated
4. ⏳ **Update frontend setup wizard** to use `/api/startup`
5. ⏳ **Add access control middleware** to enforce branch-level permissions
6. ⏳ **Audit all API endpoints** to remove unnecessary company_id parameters
7. ⏳ **Add helper functions** to get company_id from context (since there's only one)

## 📖 References

- Rule 1: ONE COMPANY = ONE DATABASE
- Rule 4: Roles assigned ONLY per branch via user_branch_roles
- Rule 6: Pricing is GLOBAL per company (no branch-level overrides)
- Rule 7: Inventory, sales, purchases, invoices are BRANCH-SPECIFIC
- Rule 9: Invoice numbers MUST include branch code

