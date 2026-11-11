#!/usr/bin/env python3
"""
Dashboard (KTR One) users are added directly in the database. This script asks for a password
(not echoed, never passed on the command line) and prints the SQL to run.

    python scripts/admin_user.py add    <username> ["Display Name"]
    python scripts/admin_user.py passwd <username>
    python scripts/admin_user.py disable <username>

Run the printed statement with psql (or any SQL client) against the kiosk database.
"""

from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MIN_PASSWORD_LENGTH = 10


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _username(raw: str) -> str:
    name = raw.strip().lower()
    if not re.fullmatch(r"[a-z0-9._@-]{3,64}", name):
        sys.exit("Username: 3-64 characters from a-z, 0-9, dot, underscore, @ or hyphen.")
    return name


def _ask_password() -> str:
    first = getpass.getpass("Password: ")
    if len(first) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if getpass.getpass("Again: ") != first:
        sys.exit("The two passwords do not match.")
    return first


def main(argv: list[str]) -> None:
    if len(argv) < 3 or argv[1] not in {"add", "passwd", "disable"}:
        sys.exit(__doc__)
    action, username = argv[1], _username(argv[2])

    if action == "disable":
        print(f"UPDATE admin_users SET is_active = false WHERE username = {_sql_str(username)};")
        return

    # Imported late so `disable` works without the app's environment variables.
    from app.core.security import hash_password

    password_hash = hash_password(_ask_password())
    if action == "add":
        display = argv[3].strip() if len(argv) > 3 else ""
        print(
            "INSERT INTO admin_users (username, password_hash, display_name) VALUES "
            f"({_sql_str(username)}, {_sql_str(password_hash)}, {_sql_str(display) if display else 'NULL'});"
        )
    else:
        print(
            f"UPDATE admin_users SET password_hash = {_sql_str(password_hash)} "
            f"WHERE username = {_sql_str(username)};"
        )


if __name__ == "__main__":
    main(sys.argv)
