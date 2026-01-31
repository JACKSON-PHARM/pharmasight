"""
Username generation utility
Generates usernames from full names in format: F-LASTNAME (e.g., "D-JACKSON", "S-WAMBUI")
"""
import re
from typing import Optional


def generate_username_from_name(full_name: Optional[str], db_session=None, existing_usernames: Optional[set] = None) -> str:
    """
    Generate a username from full name
    
    Format: First letter of first name + "-" + Last name (uppercase)
    Examples:
    - "Dr. Jackson" -> "D-JACKSON"
    - "Sarah Wambui" -> "S-WAMBUI"
    - "John Doe Smith" -> "J-SMITH" (uses last word as last name)
    
    Args:
        full_name: Full name string (e.g., "Dr. Jackson", "Sarah Wambui")
        db_session: Optional database session to check for existing usernames
        existing_usernames: Optional set of existing usernames to avoid duplicates
    
    Returns:
        Generated username (e.g., "D-JACKSON")
    """
    if not full_name or not full_name.strip():
        raise ValueError("Full name is required to generate username")
    
    # Clean and split name
    name_parts = re.split(r'\s+', full_name.strip())
    
    # Remove titles (Dr., Mr., Mrs., Ms., Prof., etc.)
    titles = {'dr', 'mr', 'mrs', 'ms', 'miss', 'prof', 'professor', 'eng', 'engineer'}
    name_parts = [part for part in name_parts if part.lower().rstrip('.') not in titles]
    
    if not name_parts:
        raise ValueError("Could not extract name parts from full name")
    
    # First letter of first name
    first_letter = name_parts[0][0].upper()
    
    # Last name (last word, uppercase)
    last_name = name_parts[-1].upper()
    
    # Remove special characters from last name (keep only letters)
    last_name = re.sub(r'[^A-Z]', '', last_name)
    
    if not last_name:
        # If no valid last name, use first name
        last_name = name_parts[0].upper()
        last_name = re.sub(r'[^A-Z]', '', last_name)
    
    # Generate base username
    base_username = f"{first_letter}-{last_name}"
    
    # Check for duplicates and append number if needed
    if existing_usernames is None:
        existing_usernames = set()
    
    if db_session:
        from app.models.user import User
        from sqlalchemy import func
        # Check database for existing usernames
        existing = db_session.query(User.username).filter(
            func.lower(User.username).like(f"{base_username.lower()}%")
        ).all()
        existing_usernames.update([u[0].lower() for u in existing if u[0]])
    
    username = base_username
    counter = 1
    while username.lower() in existing_usernames:
        username = f"{base_username}{counter}"
        counter += 1
    
    return username


def validate_username_format(username: str) -> bool:
    """
    Validate username format: Should be like "D-JACKSON" or "S-WAMBUI"
    Format: Single letter, hyphen, then uppercase letters (2-20 chars)
    """
    pattern = r'^[A-Z]-[A-Z]{2,20}$'
    return bool(re.match(pattern, username.upper()))
