#!/bin/bash

# ZeroQue Database Backup Script
# This script creates automated backups of the PostgreSQL database

set -euo pipefail

# Configuration
BACKUP_DIR="/backups/database"
RETENTION_DAYS=30
COMPRESSION="gzip"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/zeroque-backup.log"

# Database configuration
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-zeroque_dev}"
DB_USER="${DB_USER:-zeroque}"
DB_PASSWORD="${DB_PASSWORD:-zeroque}"

# S3 configuration (optional)
S3_BUCKET="${S3_BUCKET:-zeroque-backups}"
S3_REGION="${S3_REGION:-us-west-2}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "ERROR: $1"
    exit 1
}

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Function to create database backup
create_backup() {
    local backup_file="$BACKUP_DIR/zeroque_db_${TIMESTAMP}.sql"
    local compressed_file="${backup_file}.gz"
    
    log "Starting database backup..."
    
    # Set PGPASSWORD for pg_dump
    export PGPASSWORD="$DB_PASSWORD"
    
    # Create backup
    if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        --verbose --no-password --format=plain --file="$backup_file"; then
        log "Database backup created: $backup_file"
    else
        error_exit "Failed to create database backup"
    fi
    
    # Compress backup
    if [ "$COMPRESSION" = "gzip" ]; then
        if gzip "$backup_file"; then
            log "Backup compressed: $compressed_file"
            backup_file="$compressed_file"
        else
            error_exit "Failed to compress backup"
        fi
    fi
    
    # Verify backup
    if [ "$COMPRESSION" = "gzip" ]; then
        if gzip -t "$backup_file"; then
            log "Backup verification successful"
        else
            error_exit "Backup verification failed"
        fi
    fi
    
    log "Backup completed successfully: $backup_file"
    echo "$backup_file"
}

# Function to upload to S3
upload_to_s3() {
    local backup_file="$1"
    local s3_key="database/$(basename "$backup_file")"
    
    if [ -n "$AWS_ACCESS_KEY_ID" ] && [ -n "$AWS_SECRET_ACCESS_KEY" ]; then
        log "Uploading backup to S3..."
        
        if aws s3 cp "$backup_file" "s3://$S3_BUCKET/$s3_key" \
            --region "$S3_REGION" \
            --storage-class STANDARD_IA; then
            log "Backup uploaded to S3: s3://$S3_BUCKET/$s3_key"
        else
            error_exit "Failed to upload backup to S3"
        fi
    else
        log "S3 credentials not provided, skipping upload"
    fi
}

# Function to cleanup old backups
cleanup_old_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days..."
    
    find "$BACKUP_DIR" -name "zeroque_db_*.sql*" -type f -mtime +$RETENTION_DAYS -delete
    
    local deleted_count=$(find "$BACKUP_DIR" -name "zeroque_db_*.sql*" -type f -mtime +$RETENTION_DAYS | wc -l)
    log "Cleaned up $deleted_count old backup files"
}

# Function to create point-in-time recovery backup
create_pitr_backup() {
    local backup_file="$BACKUP_DIR/zeroque_pitr_${TIMESTAMP}.sql"
    local compressed_file="${backup_file}.gz"
    
    log "Starting point-in-time recovery backup..."
    
    # Set PGPASSWORD for pg_dump
    export PGPASSWORD="$DB_PASSWORD"
    
    # Create PITR backup with WAL files
    if pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        --verbose --no-password --format=plain \
        --wal-method=stream --synchronous \
        --file="$backup_file"; then
        log "PITR backup created: $backup_file"
    else
        error_exit "Failed to create PITR backup"
    fi
    
    # Compress backup
    if [ "$COMPRESSION" = "gzip" ]; then
        if gzip "$backup_file"; then
            log "PITR backup compressed: $compressed_file"
            backup_file="$compressed_file"
        else
            error_exit "Failed to compress PITR backup"
        fi
    fi
    
    log "PITR backup completed successfully: $backup_file"
    echo "$backup_file"
}

# Function to verify backup integrity
verify_backup() {
    local backup_file="$1"
    
    log "Verifying backup integrity..."
    
    if [ "${backup_file##*.}" = "gz" ]; then
        # Test compressed backup
        if gzip -t "$backup_file"; then
            log "Compressed backup integrity verified"
        else
            error_exit "Compressed backup integrity check failed"
        fi
        
        # Extract and test SQL content
        local temp_file="/tmp/verify_$(basename "$backup_file" .gz)"
        if gzip -dc "$backup_file" > "$temp_file"; then
            if head -n 10 "$temp_file" | grep -q "PostgreSQL database dump"; then
                log "SQL content verification successful"
                rm -f "$temp_file"
            else
                error_exit "SQL content verification failed"
            fi
        else
            error_exit "Failed to extract backup for verification"
        fi
    else
        # Test uncompressed backup
        if head -n 10 "$backup_file" | grep -q "PostgreSQL database dump"; then
            log "Backup integrity verified"
        else
            error_exit "Backup integrity check failed"
        fi
    fi
}

# Function to create backup metadata
create_metadata() {
    local backup_file="$1"
    local metadata_file="${backup_file}.meta"
    
    cat > "$metadata_file" << EOF
{
    "backup_type": "database",
    "timestamp": "$TIMESTAMP",
    "database": "$DB_NAME",
    "host": "$DB_HOST",
    "port": "$DB_PORT",
    "user": "$DB_USER",
    "compression": "$COMPRESSION",
    "file_size": $(stat -c%s "$backup_file"),
    "checksum": $(sha256sum "$backup_file" | cut -d' ' -f1),
    "created_by": "zeroque-backup-script",
    "version": "1.0"
}
EOF
    
    log "Metadata created: $metadata_file"
}

# Main execution
main() {
    log "Starting ZeroQue database backup process..."
    
    # Check if pg_dump is available
    if ! command -v pg_dump &> /dev/null; then
        error_exit "pg_dump not found. Please install PostgreSQL client tools."
    fi
    
    # Check if gzip is available
    if ! command -v gzip &> /dev/null; then
        error_exit "gzip not found. Please install gzip."
    fi
    
    # Create backup
    local backup_file
    backup_file=$(create_backup)
    
    # Verify backup
    verify_backup "$backup_file"
    
    # Create metadata
    create_metadata "$backup_file"
    
    # Upload to S3
    upload_to_s3 "$backup_file"
    
    # Cleanup old backups
    cleanup_old_backups
    
    log "Database backup process completed successfully"
}

# Handle script arguments
case "${1:-backup}" in
    "backup")
        main
        ;;
    "pitr")
        create_pitr_backup
        ;;
    "cleanup")
        cleanup_old_backups
        ;;
    "verify")
        if [ -z "${2:-}" ]; then
            error_exit "Please provide backup file path for verification"
        fi
        verify_backup "$2"
        ;;
    *)
        echo "Usage: $0 {backup|pitr|cleanup|verify <file>}"
        exit 1
        ;;
esac




