# Frontend Architecture - Auth & State Management

This document explains the new frontend architecture for PharmaSight, focusing on authentication, state management, and routing.

## Overview

The new architecture implements a robust, refresh-safe, multi-tab-capable authentication and state management system with the following key features:

1. **Auth Bootstrap** - Centralized auth state management
2. **Password Set Screen** - Mandatory password setup for invited users
3. **Branch Selection Flow** - Branch selection before dashboard
4. **Branch Context** - Persistent branch state with multi-tab sync
5. **Global Logout** - Comprehensive state clearing
6. **Optimistic Locking** - Version-based conflict prevention
7. **Hash Routing** - No path-based routing, prevents redirect loops

## Architecture Components

### 1. Auth Bootstrap Service (`js/services/auth_bootstrap.js`)

**Purpose**: Centralized authentication state management that runs once, is refresh-safe, and supports multiple tabs.

**Key Features**:
- Initializes Supabase client once
- Maintains auth state in memory (fast access)
- Uses BroadcastChannel for multi-tab synchronization
- Auth state listeners (reactive, no navigation inside listeners)
- Never navigates inside auth listeners (prevents loops)

**Usage**:
```javascript
// Initialize (runs once)
await AuthBootstrap.init();

// Get current user (synchronous, from cache)
const user = AuthBootstrap.getCurrentUser();

// Subscribe to auth changes
AuthBootstrap.onAuthStateChange((user, session) => {
    // Update UI, but don't navigate here!
    updateUserUI(user);
});
```

**Multi-tab Support**:
- Uses BroadcastChannel to sync auth state across tabs
- When one tab logs in/out, all tabs update immediately
- No navigation inside listeners prevents redirect loops

### 2. Password Set Screen (`js/pages/password_set.js`)

**Purpose**: Mandatory password setup for invited users before they can access the dashboard.

**Flow**:
1. User clicks invite link → Supabase authenticates
2. System detects user needs password setup (via metadata or session type)
3. Shows password set screen (blocks access to other pages)
4. User sets password → continues to branch selection

**Detection Logic**:
- Checks `session.type === 'recovery'` (password reset flow)
- Checks `user.user_metadata.needs_password_setup === true`
- Checks `user.user_metadata.invited === true` (invited users)

**Key Features**:
- Blocks dashboard access until password is set
- Validates password strength (min 8 characters)
- Confirms password match
- Updates password via Supabase `updateUser()`

### 3. Branch Selection Flow (`js/pages/branch_select.js`)

**Purpose**: Ensures user selects a branch before accessing the dashboard.

**Flow**:
1. After password set (or if branch not selected)
2. Loads available branches for user's company
3. Shows branch selection UI
4. User selects branch → continues to dashboard
5. Auto-selects if only one branch available

**Key Features**:
- Loads branches from API based on company
- Stores selection in BranchContext (persistent)
- Auto-selects single branch
- Handles no-branches case gracefully

### 4. Branch Context Manager (`js/services/branch_context.js`)

**Purpose**: Manages branch selection and persistence with multi-tab sync.

**Key Features**:
- Stores branch in localStorage + memory
- BroadcastChannel for multi-tab synchronization
- Reactive branch change listeners
- Updates CONFIG for backward compatibility

**Usage**:
```javascript
// Initialize
BranchContext.init();

// Set branch
BranchContext.setBranch(branch);

// Get branch (synchronous)
const branch = BranchContext.getBranch();

// Subscribe to changes
BranchContext.onBranchChange((branch) => {
    updateUI(branch);
});
```

**Storage**:
- localStorage key: `pharmasight_selected_branch`
- Also updates `CONFIG.BRANCH_ID` and `CONFIG.COMPANY_ID`

### 5. App State Service (`js/services/app_state.js`)

**Purpose**: Manages global app state and logout functionality.

**Key Features**:
- Clears all app state on logout
- Preserves Supabase config (for re-authentication)
- Clears localStorage, sessionStorage, branch context, CONFIG

**Usage**:
```javascript
// Global logout (clears everything)
await AppState.logout();
// or
await globalLogout();
```

**What Gets Cleared**:
- Branch selection
- Company/Branch/User IDs in CONFIG
- All localStorage items (except Supabase config)
- SessionStorage
- Redirects to login

### 6. Optimistic Locking Service (`js/services/optimistic_locking.js`)

**Purpose**: Prevents concurrent edit conflicts using version numbers.

**Key Features**:
- Extracts version from documents
- Prepares documents for save with version field
- Detects version conflicts from API responses
- Shows user-friendly conflict messages

**Usage**:
```javascript
// Save with optimistic locking
const result = await OptimisticLocking.save(
    (data) => API.items.update(itemId, data),
    document,
    {
        versionField: 'version',
        documentName: 'Item'
    }
);

if (result.success) {
    // Save successful
    document.version = result.newVersion;
} else if (result.conflict) {
    // Version conflict - user should refresh
}
```

**Version Detection**:
- Checks `document.version` or `document.updated_at`
- Compares versions before/after save
- Detects conflicts from error messages

### 7. App Router (`js/app.js` - `startAppFlow()`)

**Purpose**: Main routing logic that determines which screen to show.

**Flow**:
1. Check authentication → Login if not authenticated
2. Check password setup → Password set screen if needed
3. Check company setup → Setup wizard if needed
4. Check branch selection → Branch select if needed
5. Show dashboard (all checks passed)

**Key Features**:
- Prevents redirect loops (uses flags)
- Refresh-safe (re-evaluates on every load)
- Hash routing only (no path-based routing)
- Handles all edge cases gracefully

**Navigation Guards**:
- Protected pages require authentication
- Protected pages require branch selection
- Auth pages are accessible without branch

## File Structure

```
frontend/js/
├── services/
│   ├── auth_bootstrap.js      # Auth state management
│   ├── branch_context.js      # Branch state management
│   ├── app_state.js           # Global state & logout
│   └── optimistic_locking.js  # Version-based locking
├── pages/
│   ├── login.js               # Login page
│   ├── password_set.js        # Password setup (NEW)
│   ├── branch_select.js       # Branch selection (NEW)
│   └── ...other pages
└── app.js                     # Main router & navigation
```

## Flow Diagrams

### Login Flow
```
User opens app
    ↓
AuthBootstrap.init() → Check auth state
    ↓
Not authenticated? → Login Screen
    ↓
User logs in → AuthBootstrap.signIn()
    ↓
startAppFlow() → Check password setup
    ↓
Needs password? → Password Set Screen
    ↓
Password set → Check branch selection
    ↓
No branch? → Branch Select Screen
    ↓
Branch selected → Dashboard
```

### Invite Flow
```
User clicks invite link
    ↓
Supabase authenticates (access_token in hash)
    ↓
renderInviteHandler() processes token
    ↓
AuthBootstrap.refresh() updates state
    ↓
startAppFlow() → Needs password? → Password Set
    ↓
Password set → Branch Select → Dashboard
```

### Multi-Tab Sync
```
Tab 1: User logs in
    ↓
AuthBootstrap broadcasts auth change
    ↓
BroadcastChannel sends message
    ↓
Tab 2: Receives message
    ↓
Tab 2: Updates auth state (no navigation)
    ↓
Tab 2: UI updates automatically
```

## Key Rules & Constraints

1. **No Navigation in Auth Listeners**: Auth state listeners only update UI state, never navigate. Navigation happens in `startAppFlow()`.

2. **Hash Routing Only**: All navigation uses `window.location.hash`. No path-based routing.

3. **Refresh-Safe**: All flows survive page refresh. State is persisted in localStorage.

4. **Multi-Tab Safe**: BroadcastChannel syncs state across tabs. No conflicts.

5. **No Global Mutable State**: No `window.appState` or global mutable objects. Use services instead.

6. **Prevent Redirect Loops**: Flags like `isNavigatingFromAuth` prevent infinite loops.

## Integration with Existing Code

### Backward Compatibility

- `CONFIG.BRANCH_ID` and `CONFIG.COMPANY_ID` are still updated (for existing code)
- Old `Auth` service still exists (for backward compatibility)
- New services can coexist with old code

### Migration Path

1. **New code**: Use `AuthBootstrap` instead of `Auth`
2. **Branch access**: Use `BranchContext.getBranch()` instead of `CONFIG.BRANCH_ID`
3. **Logout**: Use `AppState.logout()` instead of `Auth.signOut()`
4. **Document saves**: Use `OptimisticLocking.save()` for editable documents

## Testing Checklist

- [ ] Login flow works
- [ ] Invite link flow works
- [ ] Password set screen appears for invited users
- [ ] Branch selection appears when no branch selected
- [ ] Branch persists across refresh
- [ ] Multi-tab sync works (login in one tab updates others)
- [ ] Logout clears all state
- [ ] Hash routing works (browser back/forward)
- [ ] No redirect loops
- [ ] Refresh-safe (all flows work after page refresh)

## Future Enhancements

- Add refresh token handling
- Add session timeout warning
- Add "Remember branch" preference
- Add branch switching without logout
- Enhance optimistic locking with retry logic
