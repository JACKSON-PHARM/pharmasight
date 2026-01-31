"""
Generate usernames for existing users who don't have one
Run this script to populate usernames for all existing users
"""
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import SessionLocal
from app.models.user import User
from app.utils.username_generator import generate_username_from_name

def generate_usernames_for_existing_users():
    """Generate usernames for all users who don't have one"""
    db: Session = SessionLocal()
    
    try:
        # Get all users without usernames
        users_without_username = db.query(User).filter(
            (User.username.is_(None)) | (User.username == '')
        ).all()
        
        print(f"Found {len(users_without_username)} users without usernames")
        
        updated_count = 0
        for user in users_without_username:
            try:
                # Generate username from full_name
                if user.full_name:
                    username = generate_username_from_name(
                        user.full_name,
                        db_session=db
                    )
                else:
                    # Fallback: use email local part
                    email_local = user.email.split('@')[0]
                    username = f"{email_local[0].upper()}-USER"
                    
                    # Check for duplicates
                    counter = 1
                    base_username = username
                    while db.query(User).filter(
                        func.lower(func.trim(User.username)) == username.lower()
                    ).filter(User.id != user.id).first():
                        username = f"{base_username}{counter}"
                        counter += 1
                
                user.username = username
                updated_count += 1
                print(f"  Generated username '{username}' for {user.email}")
                
            except Exception as e:
                print(f"  Error generating username for {user.email}: {e}")
                continue
        
        db.commit()
        print(f"\nSUCCESS: Generated usernames for {updated_count} users")
        
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    finally:
        db.close()
    
    return True

if __name__ == "__main__":
    print("Generating usernames for existing users...")
    success = generate_usernames_for_existing_users()
    sys.exit(0 if success else 1)
