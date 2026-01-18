"""
Manually insert user to bypass slow index issue
"""
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv('C:/PharmaSight/pharmasight/.env')

engine = create_engine(
    os.getenv('DATABASE_URL'),
    connect_args={'connect_timeout': 10}
)

user_id = '29932846-bf01-4bdf-9e13-25cb27764c16'
email = 'jackmwas102@gmail.com'
full_name = 'Jackson mwangi'
phone = '0708476318'

print("=" * 60)
print("Manually Inserting User")
print("=" * 60)

with engine.connect() as conn:
    # Check if user exists
    result = conn.execute(
        text("SELECT id, email FROM users WHERE id = :id"),
        {'id': user_id}
    )
    existing = result.fetchone()
    
    if existing:
        print(f"User already exists: {existing[1]}")
        print("Updating user...")
        conn.execute(
            text("""
                UPDATE users 
                SET email = :email, 
                    full_name = :full_name, 
                    phone = :phone,
                    is_active = TRUE
                WHERE id = :id
            """),
            {
                'id': user_id,
                'email': email,
                'full_name': full_name,
                'phone': phone
            }
        )
        conn.commit()
        print("User updated successfully!")
    else:
        print("Inserting new user...")
        try:
            # Try direct insert without ORM
            conn.execute(
                text("""
                    INSERT INTO users (id, email, full_name, phone, is_active)
                    VALUES (:id, :email, :full_name, :phone, TRUE)
                """),
                {
                    'id': user_id,
                    'email': email,
                    'full_name': full_name,
                    'phone': phone
                }
            )
            conn.commit()
            print("User inserted successfully!")
        except Exception as e:
            print(f"Error: {e}")
            conn.rollback()
            raise
    
    # Verify
    result = conn.execute(
        text("SELECT id, email, full_name, phone FROM users WHERE id = :id"),
        {'id': user_id}
    )
    user = result.fetchone()
    print(f"\nVerified user:")
    print(f"  ID: {user[0]}")
    print(f"  Email: {user[1]}")
    print(f"  Name: {user[2]}")
    print(f"  Phone: {user[3]}")

print("\n" + "=" * 60)
print("Done!")
