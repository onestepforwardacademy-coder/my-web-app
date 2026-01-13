#!/usr/bin/env python3
"""
User state database for multi-user Telegram bot.
Stores: invest status, positions, trades, target hits, stop losses.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "user_state.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    
    # Users table - tracks invest status
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        invest_active INTEGER DEFAULT 0,
        wallet_address TEXT,
        target_multiplier REAL DEFAULT 2.0,
        buy_amount REAL DEFAULT 0.001,
        created_at TEXT,
        updated_at TEXT
    )''')
    
    # Positions table - for live profit tracking
    c.execute('''CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        token TEXT,
        symbol TEXT,
        buy_price REAL,
        amount REAL,
        source TEXT,
        created_at TEXT,
        UNIQUE(chat_id, token)
    )''')
    
    # Trades table - active trades
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        token TEXT,
        amount REAL,
        target REAL,
        created_at TEXT,
        UNIQUE(chat_id, token)
    )''')
    
    # Target hits history
    c.execute('''CREATE TABLE IF NOT EXISTS target_hits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        token TEXT,
        profit_percent REAL,
        created_at TEXT
    )''')
    
    # Stop loss hits history
    c.execute('''CREATE TABLE IF NOT EXISTS stop_loss_hits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        token TEXT,
        loss_percent REAL,
        created_at TEXT
    )''')
    
    conn.commit()
    conn.close()
    print("Database initialized")

# User functions
def set_invest_active(chat_id, active):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT INTO users (chat_id, invest_active, created_at, updated_at) 
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(chat_id) DO UPDATE SET invest_active=?, updated_at=?''',
              (chat_id, 1 if active else 0, now, now, 1 if active else 0, now))
    conn.commit()
    conn.close()

def get_invest_active(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT invest_active FROM users WHERE chat_id=?', (chat_id,))
    row = c.fetchone()
    conn.close()
    return bool(row['invest_active']) if row else False

def get_active_investors():
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT chat_id FROM users WHERE invest_active=1')
    rows = c.fetchall()
    conn.close()
    return [row['chat_id'] for row in rows]

# Position functions
def add_position(chat_id, token, symbol, buy_price, amount, source="manual"):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT OR REPLACE INTO positions 
                 (chat_id, token, symbol, buy_price, amount, source, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?)''',
              (chat_id, token, symbol, buy_price, amount, source, now))
    conn.commit()
    conn.close()

def get_positions(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM positions WHERE chat_id=?', (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def remove_position(chat_id, token):
    conn = get_conn()
    c = conn.cursor()
    c.execute('DELETE FROM positions WHERE chat_id=? AND token=?', (chat_id, token))
    conn.commit()
    conn.close()

# Trade functions
def add_trade(chat_id, token, amount, target):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT OR REPLACE INTO trades 
                 (chat_id, token, amount, target, created_at)
                 VALUES (?, ?, ?, ?, ?)''',
              (chat_id, token, amount, target, now))
    conn.commit()
    conn.close()

def get_trades(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM trades WHERE chat_id=?', (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def remove_trade(chat_id, token):
    conn = get_conn()
    c = conn.cursor()
    c.execute('DELETE FROM trades WHERE chat_id=? AND token=?', (chat_id, token))
    conn.commit()
    conn.close()

# Cleanup function - removes token from ALL tracking
def cleanup_sold_token(chat_id, token):
    conn = get_conn()
    c = conn.cursor()
    c.execute('DELETE FROM positions WHERE chat_id=? AND token=?', (chat_id, token))
    c.execute('DELETE FROM trades WHERE chat_id=? AND token=?', (chat_id, token))
    conn.commit()
    conn.close()
    print(f"[DB] Cleaned up {token[:12]}... for user {chat_id}")

# History functions
def add_target_hit(chat_id, token, profit_percent):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT INTO target_hits (chat_id, token, profit_percent, created_at)
                 VALUES (?, ?, ?, ?)''', (chat_id, token, profit_percent, now))
    conn.commit()
    conn.close()

def add_stop_loss_hit(chat_id, token, loss_percent):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''INSERT INTO stop_loss_hits (chat_id, token, loss_percent, created_at)
                 VALUES (?, ?, ?, ?)''', (chat_id, token, loss_percent, now))
    conn.commit()
    conn.close()

def get_target_hits(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM target_hits WHERE chat_id=? ORDER BY created_at DESC LIMIT 20', (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_stop_loss_hits(chat_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM stop_loss_hits WHERE chat_id=? ORDER BY created_at DESC LIMIT 20', (chat_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: user_db.py <command> [args]")
        print("Commands: init, set_invest, get_invest, add_position, get_positions, cleanup")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "init":
        init_db()
    elif cmd == "set_invest":
        chat_id = int(sys.argv[2])
        active = sys.argv[3].lower() == "true"
        set_invest_active(chat_id, active)
        print(json.dumps({"success": True, "chat_id": chat_id, "active": active}))
    elif cmd == "get_invest":
        chat_id = int(sys.argv[2])
        active = get_invest_active(chat_id)
        print(json.dumps({"chat_id": chat_id, "active": active}))
    elif cmd == "get_active":
        investors = get_active_investors()
        print(json.dumps({"investors": investors}))
    elif cmd == "add_position":
        chat_id, token, symbol, price, amount = int(sys.argv[2]), sys.argv[3], sys.argv[4], float(sys.argv[5]), float(sys.argv[6])
        add_position(chat_id, token, symbol, price, amount)
        print(json.dumps({"success": True}))
    elif cmd == "get_positions":
        chat_id = int(sys.argv[2])
        positions = get_positions(chat_id)
        print(json.dumps(positions))
    elif cmd == "add_trade":
        chat_id, token, amount, target = int(sys.argv[2]), sys.argv[3], float(sys.argv[4]), float(sys.argv[5])
        add_trade(chat_id, token, amount, target)
        print(json.dumps({"success": True}))
    elif cmd == "get_trades":
        chat_id = int(sys.argv[2])
        trades = get_trades(chat_id)
        print(json.dumps(trades))
    elif cmd == "cleanup":
        chat_id, token = int(sys.argv[2]), sys.argv[3]
        cleanup_sold_token(chat_id, token)
        print(json.dumps({"success": True}))
    elif cmd == "remove_trade":
        chat_id, token = int(sys.argv[2]), sys.argv[3]
        remove_trade(chat_id, token)
        print(json.dumps({"success": True}))
    else:
        print(json.dumps({"error": f"Unknown command: {cmd}"}))
