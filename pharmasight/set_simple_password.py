"""
Set a password for a Supabase Auth user via the Admin API.

Usage:
  python set_simple_password.py --email user@example.com --password "secure-password"
  # Or use environment variables:
  SET_PASSWORD_EMAIL=user@example.com SET_PASSWORD_NEW_PASSWORD=secret python set_simple_password.py

Required environment variables:
  SUPABASE_URL - e.g. https://YOUR_PROJECT_REF.supabase.co
  SUPABASE_SERVICE_KEY - Service role key from Supabase Dashboard (Settings -> API)

Never commit credentials. Email and password must be provided via CLI or env, not hard-coded.
"""
import argparse
import os
import sys

import requests


def main():
    parser = argparse.ArgumentParser(
        description="Set a password for a Supabase Auth user (Admin API)."
    )
    parser.add_argument(
        "--email",
        default=os.getenv("SET_PASSWORD_EMAIL"),
        help="User email (or set SET_PASSWORD_EMAIL)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("SET_PASSWORD_NEW_PASSWORD"),
        help="New password (or set SET_PASSWORD_NEW_PASSWORD)",
    )
    parser.add_argument(
        "--supabase-url",
        default=os.getenv("SUPABASE_URL"),
        help="Supabase project URL (or set SUPABASE_URL)",
    )
    args = parser.parse_args()

    email = (args.email or "").strip()
    password = args.password
    supabase_url = (args.supabase_url or "").strip().rstrip("/")
    service_key = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()

    if not service_key:
        print("SUPABASE_SERVICE_KEY is required. Set it in your environment.", file=sys.stderr)
        print("Get it from: Supabase Dashboard -> Settings -> API -> service_role key.", file=sys.stderr)
        sys.exit(1)
    if not supabase_url:
        print("SUPABASE_URL is required (e.g. https://YOUR_PROJECT_REF.supabase.co).", file=sys.stderr)
        sys.exit(1)
    if not email:
        print("Email is required: --email user@example.com or SET_PASSWORD_EMAIL.", file=sys.stderr)
        sys.exit(1)
    if not password:
        print("Password is required: --password 'your-password' or SET_PASSWORD_NEW_PASSWORD.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("Set password for Supabase Auth user")
    print("=" * 60)
    print(f"Supabase URL: {supabase_url}")
    print(f"Email: {email}")
    print("Password: (hidden)")
    print()

    auth_url = f"{supabase_url}/auth/v1/admin/users"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            f"{auth_url}?per_page=1000",
            headers=headers,
            timeout=10,
        )
        if response.status_code != 200:
            print(f"Error getting users: {response.status_code}", file=sys.stderr)
            print(response.text, file=sys.stderr)
            sys.exit(1)

        users = response.json().get("users", [])
        user = next((u for u in users if (u.get("email") or "").lower() == email.lower()), None)

        if not user:
            print(f"User with email '{email}' not found.", file=sys.stderr)
            print("Create the user in Supabase Dashboard first, or use Supabase Auth signup.", file=sys.stderr)
            sys.exit(1)

        user_id = user.get("id")
        update_response = requests.put(
            f"{auth_url}/{user_id}",
            headers=headers,
            json={"password": password},
            timeout=10,
        )

        if update_response.status_code in (200, 201):
            print("Password updated successfully.")
            print("User can now log in with this email and the new password.")
        else:
            print(f"Error updating password: {update_response.status_code}", file=sys.stderr)
            print(update_response.text, file=sys.stderr)
            sys.exit(1)

    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)


if __name__ == "__main__":
    main()
