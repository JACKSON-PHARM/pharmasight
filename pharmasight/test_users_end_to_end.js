/**
 * End-to-End Test for Users & Roles Tab
 * 
 * Run this in browser console (F12) when on the Users & Roles tab
 * It will test every step of the data flow
 */

async function testUsersEndToEnd() {
    console.log('='.repeat(70));
    console.log('🧪 USERS & ROLES - END TO END TEST');
    console.log('='.repeat(70));
    
    let allTestsPassed = true;
    
    // ==========================================
    // TEST 1: Check if required objects exist
    // ==========================================
    console.log('\n[TEST 1] Checking required objects...');
    
    const checks = {
        'window.API': typeof window.API,
        'API.users': typeof window.API?.users,
        'API.users.list': typeof window.API?.users?.list,
        'API.users.listRoles': typeof window.API?.users?.listRoles,
        'window.loadSettings': typeof window.loadSettings,
        'window.loadSettingsSubPage': typeof window.loadSettingsSubPage,
        'window.renderUsersPage': typeof window.renderUsersPage,
        'CONFIG.API_BASE_URL': typeof CONFIG?.API_BASE_URL,
        'CONFIG.COMPANY_ID': typeof CONFIG?.COMPANY_ID,
        'CONFIG.BRANCH_ID': typeof CONFIG?.BRANCH_ID
    };
    
    for (const [name, type] of Object.entries(checks)) {
        if (type === 'undefined') {
            console.error(`❌ ${name} is undefined`);
            allTestsPassed = false;
        } else {
            console.log(`✅ ${name}: ${type}`);
        }
    }
    
    // ==========================================
    // TEST 2: Check API Base URL
    // ==========================================
    console.log('\n[TEST 2] API Configuration...');
    console.log(`API Base URL: ${CONFIG.API_BASE_URL || 'NOT SET'}`);
    console.log(`Company ID: ${CONFIG.COMPANY_ID || 'NOT SET'}`);
    console.log(`Branch ID: ${CONFIG.BRANCH_ID || 'NOT SET'}`);
    
    if (!CONFIG.API_BASE_URL) {
        console.error('❌ API_BASE_URL is not configured');
        allTestsPassed = false;
    }
    
    // ==========================================
    // TEST 3: Test Backend Health
    // ==========================================
    console.log('\n[TEST 3] Testing backend health...');
    try {
        const healthResponse = await fetch(`${CONFIG.API_BASE_URL}/health`);
        const healthData = await healthResponse.json();
        if (healthResponse.ok) {
            console.log('✅ Backend is running:', healthData);
        } else {
            console.error('❌ Backend health check failed:', healthResponse.status);
            allTestsPassed = false;
        }
    } catch (error) {
        console.error('❌ Cannot connect to backend:', error.message);
        console.error('   Make sure backend is running on', CONFIG.API_BASE_URL);
        allTestsPassed = false;
    }
    
    // ==========================================
    // TEST 4: Test API.users.listRoles()
    // ==========================================
    console.log('\n[TEST 4] Testing API.users.listRoles()...');
    try {
        const roles = await API.users.listRoles();
        console.log(`✅ Roles API works! Found ${roles.length} roles:`);
        roles.forEach(role => {
            console.log(`   - ${role.role_name}: ${role.description || 'No description'}`);
        });
    } catch (error) {
        console.error('❌ Roles API failed:', error.message);
        console.error('   Error details:', error);
        allTestsPassed = false;
    }
    
    // ==========================================
    // TEST 5: Test API.users.list()
    // ==========================================
    console.log('\n[TEST 5] Testing API.users.list()...');
    try {
        const usersResponse = await API.users.list();
        console.log(`✅ Users API works! Response structure:`, Object.keys(usersResponse));
        console.log(`   Users found: ${usersResponse.users?.length || 0}`);
        if (usersResponse.users && usersResponse.users.length > 0) {
            console.log('   First user:', {
                email: usersResponse.users[0].email,
                full_name: usersResponse.users[0].full_name,
                is_active: usersResponse.users[0].is_active,
                branch_roles: usersResponse.users[0].branch_roles?.length || 0
            });
        }
    } catch (error) {
        console.error('❌ Users API failed:', error.message);
        console.error('   Error details:', error);
        console.error('   Full error:', error);
        allTestsPassed = false;
    }
    
    // ==========================================
    // TEST 6: Test renderUsersPage function
    // ==========================================
    console.log('\n[TEST 6] Testing renderUsersPage() function...');
    try {
        const settingsPage = document.getElementById('settings');
        if (!settingsPage) {
            console.error('❌ Settings page element not found');
            allTestsPassed = false;
        } else {
            console.log('✅ Settings page element exists');
            console.log('   Current innerHTML length:', settingsPage.innerHTML?.length || 0);
            
            // Manually call renderUsersPage
            console.log('\n   Calling renderUsersPage() manually...');
            await window.renderUsersPage();
            
            // Check if content was rendered
            setTimeout(() => {
                const newLength = settingsPage.innerHTML?.length || 0;
                console.log(`   After renderUsersPage: innerHTML length = ${newLength}`);
                
                if (newLength > 100) {
                    console.log('✅ Page content rendered!');
                    console.log('   Preview:', settingsPage.innerHTML.substring(0, 200) + '...');
                } else {
                    console.error('❌ Page content not rendered (too short)');
                    console.error('   Current content:', settingsPage.innerHTML);
                }
            }, 1000);
        }
    } catch (error) {
        console.error('❌ renderUsersPage() failed:', error);
        console.error('   Stack:', error.stack);
        allTestsPassed = false;
    }
    
    // ==========================================
    // TEST 7: Check current page state
    // ==========================================
    console.log('\n[TEST 7] Checking current page state...');
    const hash = window.location.hash;
    console.log(`Current hash: ${hash}`);
    
    const settingsPage = document.getElementById('settings');
    if (settingsPage) {
        console.log('Settings page classes:', settingsPage.className);
        console.log('Settings page display:', window.getComputedStyle(settingsPage).display);
        console.log('Settings page visibility:', window.getComputedStyle(settingsPage).visibility);
    }
    
    // ==========================================
    // TEST 8: Check routing
    // ==========================================
    console.log('\n[TEST 8] Testing routing...');
    try {
        // Check if loadSettingsSubPage is being called
        const originalLoadSettingsSubPage = window.loadSettingsSubPage;
        let wasCalled = false;
        let calledWith = null;
        
        window.loadSettingsSubPage = function(subPage) {
            wasCalled = true;
            calledWith = subPage;
            console.log(`   [INTERCEPT] loadSettingsSubPage called with: ${subPage}`);
            return originalLoadSettingsSubPage.call(this, subPage);
        };
        
        // Trigger settings load
        console.log('   Triggering loadSettings with "users"...');
        await window.loadSettings('users');
        
        if (wasCalled) {
            console.log(`✅ Routing works! loadSettingsSubPage was called with: ${calledWith}`);
        } else {
            console.error('❌ Routing issue: loadSettingsSubPage was not called');
        }
        
        // Restore original
        window.loadSettingsSubPage = originalLoadSettingsSubPage;
    } catch (error) {
        console.error('❌ Routing test failed:', error);
        allTestsPassed = false;
    }
    
    // ==========================================
    // SUMMARY
    // ==========================================
    console.log('\n' + '='.repeat(70));
    if (allTestsPassed) {
        console.log('✅ ALL TESTS PASSED');
        console.log('If page is still blank, check browser console for JavaScript errors');
    } else {
        console.log('❌ SOME TESTS FAILED');
        console.log('Review errors above to identify the issue');
    }
    console.log('='.repeat(70));
    
    return {
        allTestsPassed,
        apiBaseUrl: CONFIG.API_BASE_URL,
        companyId: CONFIG.COMPANY_ID,
        branchId: CONFIG.BRANCH_ID
    };
}

// Auto-run if in browser console
if (typeof window !== 'undefined') {
    console.log('📋 To run the test, execute:');
    console.log('   testUsersEndToEnd()');
    console.log('\nOr wait 2 seconds for auto-run...');
    setTimeout(() => {
        if (window.location.hash.includes('settings-users')) {
            testUsersEndToEnd();
        }
    }, 2000);
}
