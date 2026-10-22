"""
Backs up the SQLite database to a timestamped file in ./backups/.

Run this on a schedule (cron, or your hosting platform's scheduled job
feature) — daily is a sane minimum once a real customer's data is in here.

    python -m backend.backup   (from the repository root)

To actually protect against server loss (not just local disk mistakes),
point the destination at off-server storage instead of leaving backups
sitting next to the live database:

  - Simplest: sync the backups/ folder to cloud storage with rclone
    (works with S3, Backblaze B2, Google Drive, etc.) as a second cron step:
        rclone copy backups/ remote:your-bucket/backups/

  - Or write directly to S3-compatible storage with boto3 if you'd rather
    not add rclone as a dependency — ask and this script can be extended
    to do that directly.

This script only handles the default SQLite deployment. If DATABASE_URL
points at Postgres instead, use `pg_dump` on a schedule instead of this
script.
"""
import os
import shutil
import sys
from datetime import datetime, timezone

DB_PATH = os.environ.get(
    "SQLITE_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "timetable.db"),
)
BACKUP_DIR = os.environ.get(
    "BACKUP_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups"),
)
KEEP_LAST = int(os.environ.get("BACKUP_KEEP_LAST", "30"))  # prune older backups


def main():
    if not os.path.exists(DB_PATH):
        print(f"No database found at {DB_PATH} — nothing to back up.")
        sys.exit(1)

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"timetable-{stamp}.db")
    shutil.copy2(DB_PATH, dest)
    print(f"Backed up {DB_PATH} -> {dest}")

    # prune old local backups so disk doesn't grow forever
    backups = sorted(
        (f for f in os.listdir(BACKUP_DIR) if f.startswith("timetable-") and f.endswith(".db")),
        reverse=True,
    )
    for old in backups[KEEP_LAST:]:
        os.remove(os.path.join(BACKUP_DIR, old))
        print(f"Pruned old backup: {old}")


if __name__ == "__main__":
    main()
