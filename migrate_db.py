#!/usr/bin/env python3
"""
Database migrations for the booking system.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'booking.db')

def migrate():
    print(f"Migrating database: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create category table if it doesn't exist
    print("Creating category table...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS category (
            id INTEGER PRIMARY KEY,
            name VARCHAR(50) NOT NULL UNIQUE,
            display_order INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Add category_id column to service table if it doesn't exist
    print("Adding category_id to service table...")
    try:
        cursor.execute('ALTER TABLE service ADD COLUMN category_id INTEGER REFERENCES category(id)')
        print("  Added category_id column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("  category_id column already exists")
        else:
            raise

    # Add display_order column to service table if it doesn't exist
    print("Adding display_order to service table...")
    try:
        cursor.execute('ALTER TABLE service ADD COLUMN display_order INTEGER DEFAULT 0')
        print("  Added display_order column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("  display_order column already exists")
        else:
            raise

    # Create blocked_time table if it doesn't exist
    print("Creating blocked_time table...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_time (
            id INTEGER PRIMARY KEY,
            date DATE NOT NULL,
            start_time VARCHAR(5),
            end_time VARCHAR(5),
            reason VARCHAR(100),
            is_all_day BOOLEAN DEFAULT 0,
            is_recurring_weekly BOOLEAN DEFAULT 0,
            recurring_day_of_week INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Add no_show_at column to booking table if it doesn't exist
    print("Adding no_show_at to booking table...")
    try:
        cursor.execute('ALTER TABLE booking ADD COLUMN no_show_at DATETIME')
        print("  Added no_show_at column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("  no_show_at column already exists")
        else:
            raise

    # Create user table for customer accounts
    print("Creating user table...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(120) NOT NULL UNIQUE,
            password_hash VARCHAR(256) NOT NULL,
            phone VARCHAR(20),
            date_of_birth DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1
        )
    ''')

    # Add date_of_birth column to user table if it doesn't exist
    print("Adding date_of_birth to user table...")
    try:
        cursor.execute('ALTER TABLE user ADD COLUMN date_of_birth DATE')
        print("  Added date_of_birth column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("  date_of_birth column already exists")
        else:
            raise

    # Add user_id column to booking table if it doesn't exist
    print("Adding user_id to booking table...")
    try:
        cursor.execute('ALTER TABLE booking ADD COLUMN user_id INTEGER REFERENCES user(id)')
        print("  Added user_id column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("  user_id column already exists")
        else:
            raise

    # Create aftercare table for aftercare advice
    print("Creating aftercare table...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS aftercare (
            id INTEGER PRIMARY KEY,
            service_id INTEGER REFERENCES service(id),
            title VARCHAR(200) NOT NULL,
            content TEXT NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create client_note table for admin notes on clients
    print("Creating client_note table...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_note (
            id INTEGER PRIMARY KEY,
            client_email VARCHAR(120) NOT NULL,
            client_name VARCHAR(100),
            note TEXT NOT NULL,
            is_alert BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Create index for faster lookups by email
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_client_note_email ON client_note(client_email)')

    # Add followup_sent column to booking table if it doesn't exist
    print("Adding followup_sent to booking table...")
    try:
        cursor.execute('ALTER TABLE booking ADD COLUMN followup_sent BOOLEAN DEFAULT 0')
        print("  Added followup_sent column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("  followup_sent column already exists")
        else:
            raise

    # Add day_after_sent column to booking table if it doesn't exist
    print("Adding day_after_sent to booking table...")
    try:
        cursor.execute('ALTER TABLE booking ADD COLUMN day_after_sent BOOLEAN DEFAULT 0')
        print("  Added day_after_sent column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("  day_after_sent column already exists")
        else:
            raise

    # Add day_after_blocked column to booking table if it doesn't exist
    print("Adding day_after_blocked to booking table...")
    try:
        cursor.execute('ALTER TABLE booking ADD COLUMN day_after_blocked BOOLEAN DEFAULT 0')
        print("  Added day_after_blocked column")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print("  day_after_blocked column already exists")
        else:
            raise

    conn.commit()
    conn.close()

    print("\n✓ Migration complete!")

if __name__ == '__main__':
    migrate()
