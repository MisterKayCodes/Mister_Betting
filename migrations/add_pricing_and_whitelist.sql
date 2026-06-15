-- migrations/add_pricing_and_whitelist.sql
-- Creates tables for VIP pricing, price_history, league whitelist, admin details, and reports.
-- Safe to run multiple times (uses IF NOT EXISTS).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS vip_pricing (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT DEFAULT 'default',
  base_price REAL NOT NULL,
  effective_from DATETIME NULL,
  effective_to DATETIME NULL,
  is_active INTEGER DEFAULT 1,
  created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pricing_id INTEGER,
  old_price REAL,
  new_price REAL,
  change_reason TEXT,
  changed_by TEXT,
  changed_at DATETIME DEFAULT (datetime('now')),
  FOREIGN KEY(pricing_id) REFERENCES vip_pricing(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS leagues_whitelist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  api_football_id INTEGER UNIQUE,
  league_name TEXT,
  country TEXT,
  enabled INTEGER DEFAULT 1,
  added_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS league_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fixture_id INTEGER,
  api_football_league_id INTEGER,
  league_name TEXT,
  report_reason TEXT,
  reported_at DATETIME DEFAULT (datetime('now')),
  notified_admin INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vip_compensation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  reason TEXT,
  games_awarded INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE,
  chat_id TEXT,
  is_superadmin INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT (datetime('now'))
);

-- NOTE: Altering existing 'matches' table columns is handled by the migration runner script
-- to avoid sqlite ALTER TABLE errors. This SQL file only creates new tables.
