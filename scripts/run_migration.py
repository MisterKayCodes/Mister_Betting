#!/usr/bin/env python3
"""
scripts/run_migration.py
Run this on the VPS to apply DB schema changes safely.
Usage: python scripts/run_migration.py --db /path/to/bot.db

What it does:
 - Creates a timestamped backup of the DB file
 - Executes CREATE TABLE IF NOT EXISTS statements from migrations/add_pricing_and_whitelist.sql
 - Adds missing columns to the 'matches' table (if absent)
 - Runs operations inside a transaction; on error it rolls back and restores backup

Always backup before running. Example:
  cp bot.db bot.db.before_migration
  python scripts/run_migration.py --db bot.db

"""
import argparse
import shutil
import sqlite3
import sys
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
SQL_PATH = os.path.join(BASE_DIR, 'migrations', 'add_pricing_and_whitelist.sql')

ADD_MATCH_COLUMNS = [
    ("result_fetch_retries", "INTEGER DEFAULT 0"),
    ("last_result_fetch_attempt", "DATETIME"),
    ("auto_blacklisted", "INTEGER DEFAULT 0")
]


def backup_db(db_path):
    ts = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    backup = f"{db_path}.bak.{ts}"
    shutil.copy2(db_path, backup)
    return backup


def read_sql(sql_path):
    with open(sql_path, 'r', encoding='utf-8') as f:
        return f.read()


def table_has_column(conn, table, column):
    cur = conn.execute(f"PRAGMA table_info({table});")
    cols = [row[1] for row in cur.fetchall()]
    return column in cols


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='bot.db', help='Path to SQLite DB file')
    args = p.parse_args()

    db_path = args.db
    if not os.path.exists(db_path):
        print(f"ERROR: DB not found at {db_path}")
        sys.exit(2)

    print(f"Backing up DB: {db_path}...")
    bak = backup_db(db_path)
    print(f"Backup created: {bak}")

    sql = read_sql(SQL_PATH)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        cur = conn.cursor()
        print("Beginning transaction...")
        cur.execute('BEGIN')

        print("Applying SQL file (CREATE TABLE IF NOT EXISTS)...")
        cur.executescript(sql)

        # Conditionally add columns to matches table
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matches';")
        if cur.fetchone():
            for col_name, col_def in ADD_MATCH_COLUMNS:
                if not table_has_column(conn, 'matches', col_name):
                    alter_sql = f"ALTER TABLE matches ADD COLUMN {col_name} {col_def};"
                    print(f"Adding column: {col_name}")
                    cur.execute(alter_sql)
                else:
                    print(f"Column already present: {col_name}")
        else:
            print("Warning: 'matches' table not present — skipping column additions")

        print("Committing transaction...")
        conn.commit()
        print("Migration applied successfully.")
        print("NOTE: Review the new tables: vip_pricing, price_history, leagues_whitelist, league_reports, admins")

    except Exception as e:
        print(f"Migration failed: {e}")
        print("Attempting rollback and restore from backup...")
        conn.rollback()
        conn.close()
        try:
            shutil.copy2(bak, db_path)
            print(f"DB restored from backup {bak}")
        except Exception as re:
            print(f"Failed to restore backup: {re}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
