#!/bin/bash
#
# SQLite Database Backup Script for InvestPilot
# Usage: ./tools/backup.sh
# Recommended: Set up daily cron job
#   0 3 * * * /path/to/InvestPilot/tools/backup.sh >> /var/log/investpilot-backup.log 2>&1
#

set -euo pipefail

# Configuration
DB_CONTAINER_NAME="investpilot-web-1"
DB_PATH_IN_CONTAINER="/data/db/investpilot.db"
BACKUP_DIR="/data/investpilot/backups"
KEEP_DAYS=7

# Create backup directory if not exists
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/investpilot_${TIMESTAMP}.db"

echo "[$TIMESTAMP] Starting SQLite backup..."

# Hot backup using sqlite3 .backup command (safe even during writes with WAL mode)
docker exec "$DB_CONTAINER_NAME" sqlite3 "$DB_PATH_IN_CONTAINER" ".backup '/data/backups/investpilot_${TIMESTAMP}.db'"

if [ $? -eq 0 ]; then
    echo "[$TIMESTAMP] Backup created successfully: investpilot_${TIMESTAMP}.db"

    # Compress the backup
    gzip "$BACKUP_FILE" 2>/dev/null && echo "[$TIMESTAMP] Backup compressed: investpilot_${TIMESTAMP}.db.gz" || true

    # Remove old backups (keep last KEEP_DAYS days)
    find "$BACKUP_DIR" -name "investpilot_*.db*" -mtime +$KEEP_DAYS -delete
    echo "[$TIMESTAMP] Old backups cleaned (keeping last $KEEP_DAYS days)"
else
    echo "[$TIMESTAMP] ERROR: Backup failed!"
    exit 1
fi

# Optional: Sync to remote storage (uncomment and configure)
# rclone copy "$BACKUP_DIR" remote:investpilot-backups/ --include "*.gz"
# echo "[$TIMESTAMP] Backup synced to remote storage"

echo "[$TIMESTAMP] Backup completed."
