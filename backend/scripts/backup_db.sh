#!/bin/bash
# Database backup script for trading platform
# Usage: ./scripts/backup_db.sh
# Recommended: run via cron every 6 hours
#   0 */6 * * * /path/to/backup_db.sh

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5434}"
DB_NAME="${DB_NAME:-trading_db}"
DB_USER="${DB_USER:-trading}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/trading_db_${TIMESTAMP}.sql.gz"

# Create backup directory
mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting database backup..."

# Dump and compress
PGPASSWORD="${PGPASSWORD:-trading_secret}" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --no-owner \
    --no-privileges \
    | gzip > "$BACKUP_FILE"

echo "[$(date)] Backup created: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

# Clean up old backups
find "$BACKUP_DIR" -name "trading_db_*.sql.gz" -mtime +$RETENTION_DAYS -delete
echo "[$(date)] Cleaned backups older than $RETENTION_DAYS days"

echo "[$(date)] Backup complete."
