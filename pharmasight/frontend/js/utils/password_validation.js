/**
 * Password Validation Utility
 * 
 * Consistent password validation rules across the application:
 * - Minimum 6 characters (not 8)
 * - Cannot be numbers only
 * - Cannot be letters only
 * - Cannot be sequential characters
 * - Cannot be common passwords
 */

const PasswordValidation = {
    // Common passwords to reject
    COMMON_PASSWORDS: [
        'password', '123456', '12345678', 'qwerty', 'abc123', 'password123',
        'admin', 'letmein', 'welcome', 'monkey', '1234567890', '1234567',
        'sunshine', 'princess', 'dragon', 'passw0rd', 'master', 'hello',
        'freedom', 'whatever', 'qazwsx', 'trustno1', '654321', 'jordan23',
        'harley', 'password1', '1234', 'shadow', 'superman', 'qwerty123',
        'michael', 'football', 'iloveyou', '123123', 'welcome123', 'login'
    ],

    /**
     * Check if password is numbers only
     */
    isNumbersOnly(password) {
        return /^\d+$/.test(password);
    },

    /**
     * Check if password is letters only
     */
    isLettersOnly(password) {
        return /^[a-zA-Z]+$/.test(password);
    },

    /**
     * Check if password contains sequential characters
     * Examples: "123456", "abcdef", "987654", "zyxwvu"
     */
    hasSequentialChars(password) {
        if (password.length < 3) return false;
        
        const lower = password.toLowerCase();
        
        // Check for sequential numbers
        for (let i = 0; i < lower.length - 2; i++) {
            const char1 = lower.charCodeAt(i);
            const char2 = lower.charCodeAt(i + 1);
            const char3 = lower.charCodeAt(i + 2);
            
            // Check forward sequence (e.g., 123, abc)
            if (char2 === char1 + 1 && char3 === char2 + 1) {
                // Verify they're all the same type (all numbers or all letters)
                const isNum1 = char1 >= 48 && char1 <= 57;
                const isNum2 = char2 >= 48 && char2 <= 57;
                const isNum3 = char3 >= 48 && char3 <= 57;
                const isLetter1 = char1 >= 97 && char1 <= 122;
                const isLetter2 = char2 >= 97 && char2 <= 122;
                const isLetter3 = char3 >= 97 && char3 <= 122;
                
                if ((isNum1 && isNum2 && isNum3) || (isLetter1 && isLetter2 && isLetter3)) {
                    return true;
                }
            }
            
            // Check reverse sequence (e.g., 321, cba)
            if (char2 === char1 - 1 && char3 === char2 - 1) {
                const isNum1 = char1 >= 48 && char1 <= 57;
                const isNum2 = char2 >= 48 && char2 <= 57;
                const isNum3 = char3 >= 48 && char3 <= 57;
                const isLetter1 = char1 >= 97 && char1 <= 122;
                const isLetter2 = char2 >= 97 && char2 <= 122;
                const isLetter3 = char3 >= 97 && char3 <= 122;
                
                if ((isNum1 && isNum2 && isNum3) || (isLetter1 && isLetter2 && isLetter3)) {
                    return true;
                }
            }
        }
        
        return false;
    },

    /**
     * Check if password is a common password
     */
    isCommonPassword(password) {
        const lower = password.toLowerCase();
        return this.COMMON_PASSWORDS.includes(lower);
    },

    /**
     * Validate password against all rules
     * Returns: { valid: boolean, errors: string[] }
     */
    validate(password) {
        const errors = [];
        
        if (!password || typeof password !== 'string') {
            return { valid: false, errors: ['Password is required'] };
        }
        
        // Minimum length: 6 characters
        if (password.length < 6) {
            errors.push('Password must be at least 6 characters long');
        }
        
        // Cannot be numbers only
        if (this.isNumbersOnly(password)) {
            errors.push('Password cannot be numbers only');
        }
        
        // Cannot be letters only
        if (this.isLettersOnly(password)) {
            errors.push('Password cannot be letters only');
        }
        
        // Cannot be sequential
        if (this.hasSequentialChars(password)) {
            errors.push('Password cannot contain sequential characters (e.g., "123456" or "abcdef")');
        }
        
        // Cannot be common password
        if (this.isCommonPassword(password)) {
            errors.push('Password is too common. Please choose a more secure password');
        }
        
        return {
            valid: errors.length === 0,
            errors: errors
        };
    },

    /**
     * Get first error message (for inline display)
     */
    getFirstError(password) {
        const validation = this.validate(password);
        return validation.errors.length > 0 ? validation.errors[0] : '';
    },

    /**
     * Real-time validation helper for input fields
     * Returns error message or empty string
     */
    validateRealTime(password) {
        if (!password || password.length === 0) {
            return ''; // Don't show error for empty field
        }
        
        if (password.length < 6) {
            return 'Password must be at least 6 characters long';
        }
        
        if (this.isNumbersOnly(password)) {
            return 'Cannot be numbers only';
        }
        
        if (this.isLettersOnly(password)) {
            return 'Cannot be letters only';
        }
        
        if (this.hasSequentialChars(password)) {
            return 'Cannot contain sequential characters';
        }
        
        if (this.isCommonPassword(password)) {
            return 'Password is too common';
        }
        
        return ''; // Valid
    }
};

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.PasswordValidation = PasswordValidation;
}

// Export for Node.js/ES6 modules if needed
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PasswordValidation;
}
