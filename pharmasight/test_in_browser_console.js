/**
 * Copy and paste this ENTIRE script into browser console (F12)
 * when on the Users & Roles tab to test everything step by step
 */

(async function testUsersTab() {
    console.log('='.repeat(70));
    console.log('TESTING USERS & ROLES TAB - Step by Step');
    console.log('='.repeat(70));
    
    // STEP 1: Check if functions exist
    console.log('\n[STEP 1] Checking if functions exist...');
    console.log('window.loadSettings:', typeof window.loadSettings);
    console.log('window.loadSettingsSubPage:', typeof window.loadSettingsSubPage);
    console.log('window.renderUsersPage:', typeof window.renderUsersPage);
    console.log('API.users:', typeof window.API?.users);
    console.log('API.users.list:', typeof window.API?.users?.list);
    
    // STEP 2: Check configuration
    console.log('\n[STEP 2] Checking configuration...');
    console.log('API Base URL:', CONFIG.API_BASE_URL);
    console.log('Company ID:', CONFIG.COMPANY_ID);
    console.log('Branch ID:', CONFIG.BRANCH_ID);
    
    // STEP 3: Check current page
    console.log('\n[STEP 3] Checking page element...');
    const settingsPage = document.getElementById('settings');
    if (settingsPage) {
        console.log('✅ Settings page element found');
        console.log('   Current content length:', settingsPage.innerHTML?.length || 0);
        console.log('   Is active?', settingsPage.classList.contains('active'));
    } else {
        console.error('❌ Settings page element NOT found!');
        return;
    }
    
    // STEP 4: Test API calls
    console.log('\n[STEP 4] Testing API calls...');
    
    // Test roles
    try {
        console.log('Calling API.users.listRoles()...');
        const roles = await API.users.listRoles();
        console.log('✅ Roles API works! Found', roles.length, 'roles');
        console.log('   Roles:', roles.map(r => r.role_name).join(', '));
    } catch (error) {
        console.error('❌ Roles API failed:', error.message);
        console.error('   Full error:', error);
        return;
    }
    
    // Test users
    try {
        console.log('Calling API.users.list()...');
        const usersResponse = await API.users.list();
        console.log('✅ Users API works!');
        console.log('   Response keys:', Object.keys(usersResponse));
        console.log('   Users count:', usersResponse.users?.length || 0);
        if (usersResponse.users && usersResponse.users.length > 0) {
            console.log('   First user email:', usersResponse.users[0].email);
        }
    } catch (error) {
        console.error('❌ Users API failed:', error.message);
        console.error('   Full error:', error);
        return;
    }
    
    // STEP 5: Test renderUsersPage function
    console.log('\n[STEP 5] Testing renderUsersPage() function...');
    try {
        console.log('Calling window.renderUsersPage()...');
        await window.renderUsersPage();
        
        // Wait a bit for rendering
        await new Promise(resolve => setTimeout(resolve, 500));
        
        // Check result
        const page = document.getElementById('settings');
        const contentLength = page?.innerHTML?.length || 0;
        const hasUsersText = page?.innerHTML?.includes('Users & Roles');
        
        console.log('   After renderUsersPage():');
        console.log('   Content length:', contentLength);
        console.log('   Has "Users & Roles" text:', hasUsersText);
        
        if (contentLength > 100 && hasUsersText) {
            console.log('✅ Page rendered successfully!');
            console.log('   Preview:', page.innerHTML.substring(0, 150) + '...');
        } else {
            console.error('❌ Page did not render correctly');
            console.error('   Content:', page?.innerHTML?.substring(0, 200));
        }
    } catch (error) {
        console.error('❌ renderUsersPage() failed:', error);
        console.error('   Stack:', error.stack);
    }
    
    // STEP 6: Test routing
    console.log('\n[STEP 6] Testing routing...');
    console.log('Current hash:', window.location.hash);
    console.log('Current subpage:', typeof currentSettingsSubPage !== 'undefined' ? currentSettingsSubPage : 'undefined');
    
    // STEP 7: Manual trigger
    console.log('\n[STEP 7] Manually triggering loadSettingsSubPage("users")...');
    try {
        await window.loadSettingsSubPage('users');
        console.log('✅ loadSettingsSubPage("users") completed');
    } catch (error) {
        console.error('❌ loadSettingsSubPage("users") failed:', error);
    }
    
    console.log('\n' + '='.repeat(70));
    console.log('TEST COMPLETE - Check results above');
    console.log('='.repeat(70));
})();
