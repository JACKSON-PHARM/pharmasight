#!/usr/bin/env python3
"""
Generate a secure secret key for PharmaSight
Run: python generate-secret-key.py
"""

import secrets

def generate_secret_key():
    """Generate a secure random secret key"""
    key = secrets.token_urlsafe(32)
    print("\n" + "="*60)
    print("Generated Secret Key (copy this for Render SECRET_KEY):")
    print("="*60)
    print(key)
    print("="*60)
    print("\n[OK] Copy this key and paste it as SECRET_KEY value in Render")
    print("[!] Keep this key secure - don't share it publicly!")
    print("\n")
    return key

if __name__ == "__main__":
    generate_secret_key()

