-- Generate usernames for existing users who don't have one
-- Format: First letter of first name + "-" + Last name
-- Example: "Dr. Jackson" -> "D-JACKSON", "Sarah Wambui" -> "S-WAMBUI"

UPDATE users
SET username = (
    SELECT 
        CASE 
            -- If full_name exists and has multiple words
            WHEN full_name IS NOT NULL AND array_length(string_to_array(trim(full_name), ' '), 1) > 1 THEN
                -- Extract first letter of first word and last word
                UPPER(LEFT(trim(split_part(full_name, ' ', 1)), 1)) || '-' || 
                UPPER(REGEXP_REPLACE(split_part(trim(full_name), ' ', array_length(string_to_array(trim(full_name), ' '), 1)), '[^A-Za-z]', '', 'g'))
            -- If full_name exists but only one word, use first letter + word
            WHEN full_name IS NOT NULL THEN
                UPPER(LEFT(trim(full_name), 1)) || '-' || UPPER(REGEXP_REPLACE(trim(full_name), '[^A-Za-z]', '', 'g'))
            -- Fallback: use first letter of email local part + "USER"
            ELSE
                UPPER(LEFT(split_part(email, '@', 1), 1)) || '-USER'
        END
)
WHERE username IS NULL OR username = '';

-- Handle duplicates by appending numbers
DO $$
DECLARE
    user_rec RECORD;
    base_username TEXT;
    new_username TEXT;
    counter INTEGER;
BEGIN
    FOR user_rec IN 
        SELECT id, username, email, full_name 
        FROM users 
        WHERE username IS NOT NULL
        ORDER BY created_at
    LOOP
        base_username := user_rec.username;
        new_username := base_username;
        counter := 1;
        
        -- Check for duplicates and append number if needed
        WHILE EXISTS (
            SELECT 1 FROM users 
            WHERE username = new_username 
            AND id != user_rec.id
        ) LOOP
            new_username := base_username || counter::TEXT;
            counter := counter + 1;
        END LOOP;
        
        -- Update if username changed
        IF new_username != user_rec.username THEN
            UPDATE users SET username = new_username WHERE id = user_rec.id;
        END IF;
    END LOOP;
END $$;

-- Create index on username if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

COMMENT ON COLUMN users.username IS 'Unique username for login. Format: FirstLetter-LastName (e.g., D-JACKSON, S-WAMBUI)';
