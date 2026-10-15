"""Create the .env file from .env.example with secure random secrets.

Usage (from the CineBook folder):
    python scripts/create_env.py            # creates .env (refuses to overwrite)
    python scripts/create_env.py --force    # regenerates .env (old secrets are lost)
"""
from __future__ import annotations

import argparse
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def random_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing .env")
    args = parser.parse_args()

    example, target = ROOT / ".env.example", ROOT / ".env"
    if target.exists() and not args.force:
        print(f".env already exists at {target}. Use --force to regenerate it.")
        return 1
    admin_password = random_password()
    lines = []
    for line in example.read_text(encoding="utf-8").splitlines():
        if line.startswith("JWT_SECRET="):
            line = "JWT_SECRET=" + secrets.token_urlsafe(48)
        elif line.startswith("ADMIN_PASSWORD="):
            line = "ADMIN_PASSWORD=" + admin_password
        lines.append(line)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    email = next((ln.split("=", 1)[1] for ln in lines if ln.startswith("ADMIN_EMAIL=")), "admin@cinebook.app")
    print(f"Created {target}")
    print("Demo administrator login (also stored in .env):")
    print(f"   e-mail:   {email}")
    print(f"   password: {admin_password}")
    print("The admin account is created the first time you run the seed script or start the API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
