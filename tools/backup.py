#!/usr/bin/env python3
"""
InvestPilot Database Backup & Restore Script

Usage:
    python backup.py backup   [--url URL] [--dir DIR]    # Download DB backup
    python backup.py restore  [--url URL] [--file FILE]  # Upload DB to restore
    python backup.py verify   [--file FILE]              # Verify a backup file locally
    python backup.py list     [--dir DIR]                # List local backups

Examples:
    # Backup from remote server
    python backup.py backup --url https://your-server.com

    # Backup from local dev server
    python backup.py backup

    # Restore to remote server
    python backup.py restore --url https://your-server.com --file backups/investpilot_backup_20260210.db

    # Verify a backup file
    python backup.py verify --file backups/investpilot_backup_20260210.db

    # List all local backups
    python backup.py list
"""

import argparse
import json
import os
import sys
import sqlite3
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("❌ 'requests' package is required. Install it with: pip install requests")
    sys.exit(1)

# Default configuration
DEFAULT_URL = "http://localhost:5000"
DEFAULT_BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")


def format_size(size_bytes):
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def verify_sqlite(filepath):
    """Verify a file is a valid SQLite database and print table info."""
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return False

    file_size = os.path.getsize(filepath)
    print(f"📄 File: {filepath}")
    print(f"📏 Size: {format_size(file_size)}")

    # Check SQLite header magic bytes
    with open(filepath, 'rb') as f:
        header = f.read(16)
    if not header.startswith(b'SQLite format 3'):
        print("❌ Not a valid SQLite database (header mismatch)")
        return False

    try:
        conn = sqlite3.connect(filepath)

        # Integrity check
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result[0] != 'ok':
            print(f"❌ Integrity check failed: {result[0]}")
            conn.close()
            return False
        print("✅ Integrity check: PASSED")

        # List tables and row counts
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        print(f"\n📊 Tables ({len(tables)}):")
        print(f"  {'Table':<35} {'Rows':>8}")
        print(f"  {'─' * 35} {'─' * 8}")
        total_rows = 0
        for (table_name,) in tables:
            try:
                count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
                total_rows += count
                print(f"  {table_name:<35} {count:>8,}")
            except Exception:
                print(f"  {table_name:<35} {'error':>8}")
        print(f"  {'─' * 35} {'─' * 8}")
        print(f"  {'TOTAL':<35} {total_rows:>8,}")

        conn.close()
        return True

    except sqlite3.DatabaseError as e:
        print(f"❌ SQLite error: {e}")
        return False


def do_backup(url, backup_dir):
    """Download a backup from the server."""
    os.makedirs(backup_dir, exist_ok=True)

    api_url = f"{url.rstrip('/')}/api/backup"
    print(f"🔄 Downloading backup from: {api_url}")
    print(f"   Saving to: {backup_dir}/")

    start = time.time()
    try:
        resp = requests.get(api_url, stream=True, timeout=120)
    except requests.ConnectionError:
        print(f"\n❌ Cannot connect to {url}")
        print("   Make sure the server is running.")
        return False
    except requests.Timeout:
        print(f"\n❌ Request timed out after 120 seconds")
        return False

    if resp.status_code != 200:
        print(f"\n❌ Server returned HTTP {resp.status_code}")
        try:
            error = resp.json()
            print(f"   Error: {error.get('error', 'Unknown')}")
        except Exception:
            print(f"   Body: {resp.text[:200]}")
        return False

    # Determine filename from Content-Disposition header or generate one
    cd = resp.headers.get('Content-Disposition', '')
    if 'filename=' in cd:
        filename = cd.split('filename=')[-1].strip('" ')
    else:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"investpilot_backup_{timestamp}.db"

    filepath = os.path.join(backup_dir, filename)

    # Stream download with progress
    total = int(resp.headers.get('content-length', 0))
    downloaded = 0
    with open(filepath, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded / total * 100
                    bar = '█' * int(pct // 2) + '░' * (50 - int(pct // 2))
                    print(f"\r   [{bar}] {pct:.1f}% ({format_size(downloaded)}/{format_size(total)})", end='', flush=True)
                else:
                    print(f"\r   Downloaded: {format_size(downloaded)}", end='', flush=True)

    elapsed = time.time() - start
    print(f"\n\n✅ Backup saved: {filepath}")
    print(f"   Size: {format_size(os.path.getsize(filepath))}")
    print(f"   Time: {elapsed:.1f}s")

    # Save metadata (source URL, timestamp) alongside the .db file
    meta_path = filepath + '.meta'
    meta = {
        'source_url': url,
        'backup_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'file_size': os.path.getsize(filepath),
    }
    try:
        with open(meta_path, 'w') as mf:
            json.dump(meta, mf, indent=2)
    except Exception:
        pass  # Non-critical, skip silently

    # Auto-verify
    print(f"\n{'─' * 50}")
    print("🔍 Verifying backup...")
    verify_sqlite(filepath)

    return True


def do_restore(url, filepath):
    """Upload a backup file to restore on the server."""
    if not os.path.exists(filepath):
        print(f"❌ File not found: {filepath}")
        return False

    file_size = os.path.getsize(filepath)

    # Pre-verify locally before uploading
    print("🔍 Pre-verifying backup file...")
    if not verify_sqlite(filepath):
        print("\n❌ File is not a valid SQLite database. Aborting restore.")
        return False

    print(f"\n{'─' * 50}")
    print(f"⚠️  WARNING: This will REPLACE the entire database on the server!")
    print(f"   Server: {url}")
    print(f"   File:   {filepath} ({format_size(file_size)})")
    confirm = input("\n   Type 'yes' to confirm: ").strip().lower()
    if confirm != 'yes':
        print("   Restore cancelled.")
        return False

    api_url = f"{url.rstrip('/')}/api/restore"
    print(f"\n🔄 Uploading to: {api_url}")

    start = time.time()
    try:
        with open(filepath, 'rb') as f:
            resp = requests.post(
                api_url,
                files={'file': (os.path.basename(filepath), f, 'application/octet-stream')},
                timeout=300
            )
    except requests.ConnectionError:
        print(f"\n❌ Cannot connect to {url}")
        return False
    except requests.Timeout:
        print(f"\n❌ Upload timed out after 300 seconds")
        return False

    elapsed = time.time() - start

    if resp.status_code == 200:
        result = resp.json()
        print(f"\n✅ Restore successful!")
        print(f"   Message: {result.get('message', 'OK')}")
        print(f"   Size: {format_size(result.get('file_size_bytes', 0))}")
        print(f"   Time: {elapsed:.1f}s")
        if result.get('note'):
            print(f"   ℹ️  {result['note']}")
        return True
    else:
        print(f"\n❌ Restore failed (HTTP {resp.status_code})")
        try:
            error = resp.json()
            print(f"   Error: {error.get('error', 'Unknown')}")
        except Exception:
            print(f"   Body: {resp.text[:200]}")
        return False


def _read_meta(db_filepath):
    """Read the .meta JSON file associated with a backup .db file."""
    meta_path = db_filepath + '.meta'
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r') as mf:
                return json.load(mf)
        except Exception:
            pass
    return {}


def do_list(backup_dir):
    """List all backup files in the backup directory."""
    if not os.path.exists(backup_dir):
        print(f"📁 Backup directory does not exist: {backup_dir}")
        return

    files = sorted(
        [f for f in os.listdir(backup_dir) if f.endswith('.db')],
        reverse=True
    )

    if not files:
        print(f"📁 No backup files found in: {backup_dir}")
        return

    print(f"📁 Backups in: {backup_dir}")
    print(f"   {'#':<4} {'Filename':<45} {'Size':>10}  {'Modified':<19}  {'Source URL'}")
    print(f"   {'─' * 4} {'─' * 45} {'─' * 10}  {'─' * 19}  {'─' * 30}")

    for i, filename in enumerate(files, 1):
        fpath = os.path.join(backup_dir, filename)
        size = os.path.getsize(fpath)
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime('%Y-%m-%d %H:%M:%S')
        meta = _read_meta(fpath)
        source_url = meta.get('source_url', '-')
        print(f"   {i:<4} {filename:<45} {format_size(size):>10}  {mtime:<19}  {source_url}")

    print(f"\n   Total: {len(files)} backup(s)")


def main():
    parser = argparse.ArgumentParser(
        description="InvestPilot Database Backup & Restore Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python backup.py backup                          # Backup from localhost:5000
  python backup.py backup --url https://my-server  # Backup from remote
  python backup.py restore --file backups/xxx.db   # Restore to localhost
  python backup.py verify --file backups/xxx.db    # Verify backup integrity
  python backup.py list                            # List local backups
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # backup command
    p_backup = subparsers.add_parser('backup', help='Download a database backup')
    p_backup.add_argument('--url', default=DEFAULT_URL, help=f'Server URL (default: {DEFAULT_URL})')
    p_backup.add_argument('--dir', default=DEFAULT_BACKUP_DIR, help=f'Backup directory (default: ./backups)')

    # restore command
    p_restore = subparsers.add_parser('restore', help='Restore database from a backup file')
    p_restore.add_argument('--url', default=DEFAULT_URL, help=f'Server URL (default: {DEFAULT_URL})')
    p_restore.add_argument('--file', required=True, help='Path to the backup .db file')

    # verify command
    p_verify = subparsers.add_parser('verify', help='Verify a backup file locally')
    p_verify.add_argument('--file', required=True, help='Path to the .db file to verify')

    # list command
    p_list = subparsers.add_parser('list', help='List local backup files')
    p_list.add_argument('--dir', default=DEFAULT_BACKUP_DIR, help=f'Backup directory (default: ./backups)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    print("=" * 50)
    print("  InvestPilot Backup & Restore Tool")
    print("=" * 50)
    print()

    if args.command == 'backup':
        success = do_backup(args.url, args.dir)
    elif args.command == 'restore':
        success = do_restore(args.url, args.file)
    elif args.command == 'verify':
        success = verify_sqlite(args.file)
    elif args.command == 'list':
        do_list(args.dir)
        success = True
    else:
        parser.print_help()
        success = False

    print()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
