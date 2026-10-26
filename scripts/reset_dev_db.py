"""Delete the development SQLite database and migrate a fresh one (never seeds).

Refuses unless the settings are config.settings.dev, the database is SQLite inside the
project folder, and no development server is listening or holding the file.
"""

import os
import socket
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEV_SETTINGS = "config.settings.dev"
DEV_SERVER = ("127.0.0.1", 8000)
SQLITE_COMPANIONS = ("-journal", "-wal", "-shm")


def fail(message: str) -> None:
    print(f"reset-db: {message}", file=sys.stderr)
    sys.exit(1)


def dev_database_path() -> Path:
    from django.conf import settings

    database = settings.DATABASES["default"]
    if not database["ENGINE"].endswith("sqlite3"):
        fail("the default database is not SQLite; refusing to touch it.")
    path = Path(database["NAME"]).resolve()
    if not path.is_relative_to(BASE_DIR):
        fail(f"{path} is outside the project folder; refusing to touch it.")
    return path


def server_is_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(DEV_SERVER) == 0


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", DEV_SETTINGS)
    if os.environ["DJANGO_SETTINGS_MODULE"] != DEV_SETTINGS:
        fail(f"DJANGO_SETTINGS_MODULE must be {DEV_SETTINGS}.")
    sys.path.insert(0, str(BASE_DIR))

    import django
    from django.core.management import call_command

    django.setup()
    path = dev_database_path()
    if server_is_running():
        host, port = DEV_SERVER
        fail(f"a server is listening on {host}:{port}; stop it first.")
    for file in [path, *(path.with_name(path.name + suffix) for suffix in SQLITE_COMPANIONS)]:
        try:
            file.unlink(missing_ok=True)
        except PermissionError:
            fail(f"{file.name} is in use by another process; close it first.")
    print(f"reset-db: deleted {path.relative_to(BASE_DIR)}")
    call_command("migrate")


if __name__ == "__main__":
    main()
