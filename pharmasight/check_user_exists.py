"""
Check if user exists in database
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

with engine.connect() as conn:
    result = conn.execute(
        text("SELECT id, email, full_name FROM users WHERE id = :id"),
        {'id': user_id}
    )
    row = result.fetchone()
    
    if row:
        print(f"User EXISTS:")
        print(f"  ID: {row[0]}")
        print(f"  Email: {row[1]}")
        print(f"  Name: {row[2]}")
    else:
        print("User does NOT exist")
        
    # Check table size
    result = conn.execute(text("SELECT COUNT(*) FROM users"))
    count = result.scalar()
    print(f"\nTotal users in table: {count}")
