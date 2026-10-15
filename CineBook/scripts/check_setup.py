"""Diagnose a CineBook installation. Run from the CineBook folder:  python scripts/check_setup.py"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK, BAD, WARN = "[ OK ]", "[FAIL]", "[WARN]"
problems = 0


def report(ok: bool, msg: str, fix: str = "", warn: bool = False) -> None:
    global problems
    if ok:
        print(f"{OK} {msg}")
    else:
        print(f"{WARN if warn else BAD} {msg}")
        if fix:
            print(f"       -> {fix}")
        if not warn:
            problems += 1


print("CineBook setup check\n")
report(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "Install Python 3.10 - 3.13 from python.org")
in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
report(in_venv, "Virtual environment active", r"Run  venv\Scripts\activate  first", warn=True)

missing = []
for mod in ("fastapi", "uvicorn", "pymongo", "pydantic_settings", "bcrypt", "jwt", "qrcode", "reportlab",
            "streamlit", "plotly", "pandas", "requests", "dotenv", "email_validator", "pytest", "mongomock"):
    try:
        importlib.import_module(mod)
    except ImportError:
        missing.append(mod)
report(not missing, "Python packages installed" + (f" (missing: {', '.join(missing)})" if missing else ""),
       "pip install -r requirements.txt")

env = ROOT / ".env"
report(env.exists(), ".env file present", "python scripts/create_env.py")
if env.exists() and not missing:
    from backend.config import get_settings

    s = get_settings()
    try:
        s.validate_security()
        report(True, "JWT_SECRET configured")
    except RuntimeError as exc:
        report(False, str(exc))
    report(bool(s.admin_email and s.admin_password), f"Admin account configured ({s.admin_email or '-'})",
           "Set ADMIN_EMAIL and ADMIN_PASSWORD in .env")

    from backend.database import get_client, ping, server_supports_transactions

    if ping():
        info = get_client().server_info()
        report(True, f"MongoDB reachable at {s.mongo_url} (server {info.get('version')})")
        tx = server_supports_transactions()
        report(tx, "Multi-document transactions " + ("available (replica set)" if tx else
               "not available (standalone server) - CineBook uses atomic operations instead"), warn=True)
        from backend.database import get_db

        db = get_db()
        report(db.movies.count_documents({}) > 0, f"Sample data loaded in '{db.name}'",
               "python scripts/seed_data.py", warn=True)
    else:
        report(False, f"MongoDB NOT reachable at {s.mongo_url}",
               "Start the 'MongoDB Server' Windows service (services.msc) or check MONGO_URL in .env")

    try:
        import requests

        r = requests.get(s.public_api_url.rstrip("/") + "/api/health", timeout=3)
        report(r.ok, f"Backend API running at {s.public_api_url}")
    except Exception:  # noqa: BLE001
        report(False, f"Backend API not running at {s.public_api_url} (fine if you have not started it yet)",
               "uvicorn backend.main:app --reload --port 8000", warn=True)

print("\nAll essential checks passed." if not problems else f"\n{problems} problem(s) found - see the hints above.")
sys.exit(1 if problems else 0)
