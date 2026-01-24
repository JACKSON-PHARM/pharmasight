/**
 * Quick Test Script - Run in Browser Console
 * 
 * This tests if window.loadSettings exists and why it might not
 */

console.log('='.repeat(70));
console.log('TEST: window.loadSettings Availability');
console.log('='.repeat(70));

// Test 1: Check if it exists
console.log('\n[TEST 1] Checking window.loadSettings...');
console.log('typeof window.loadSettings:', typeof window.loadSettings);

if (typeof window.loadSettings === 'undefined') {
    console.error('❌ window.loadSettings is NOT defined!');
    
    // Test 2: Check if loadSettings function exists (without window)
    console.log('\n[TEST 2] Checking if loadSettings function exists (not on window)...');
    console.log('typeof loadSettings:', typeof loadSettings);
    
    // Test 3: Check settings.js loaded
    console.log('\n[TEST 3] Checking if settings.js loaded...');
    const scripts = Array.from(document.querySelectorAll('script'));
    const settingsScript = scripts.find(s => s.src && s.src.includes('settings.js'));
    if (settingsScript) {
        console.log('✅ settings.js script tag found:', settingsScript.src);
    } else {
        console.error('❌ settings.js script tag NOT found!');
    }
    
    // Test 4: Try to manually export (if function exists)
    console.log('\n[TEST 4] Attempting manual export...');
    if (typeof loadSettings === 'function') {
        console.log('✅ loadSettings function exists (not on window)');
        console.log('   Manually exporting to window...');
        window.loadSettings = loadSettings;
        window.loadSettingsSubPage = loadSettingsSubPage;
        window.renderUsersPage = renderUsersPage;
        console.log('✅ Manual export complete!');
        console.log('   Now try navigating to Users & Roles tab again');
    } else {
        console.error('❌ loadSettings function does not exist at all!');
        console.error('   settings.js might have a JavaScript error');
        console.error('   Check console for red error messages');
    }
} else {
    console.log('✅ window.loadSettings EXISTS!');
    console.log('   If page is still blank, the issue is elsewhere');
    console.log('   Try calling: window.loadSettingsSubPage("users")');
}

console.log('\n' + '='.repeat(70));
console.log('Test Complete');
console.log('='.repeat(70));
