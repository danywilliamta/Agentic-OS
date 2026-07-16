"""
Initialize SQLite database with test data for inventory agent testing.
"""

import sqlite3
from datetime import datetime

DB_PATH = "test_inventory.db"


def init_database():
    """Create tables and insert test data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            company TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT UNIQUE NOT NULL,
            qty INTEGER NOT NULL,
            unit_price REAL NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            devis_raw_id INTEGER,
            user_id INTEGER,
            devis_number TEXT UNIQUE NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (devis_raw_id) REFERENCES devis_raw(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devis_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            devis_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            line_total REAL NOT NULL,
            FOREIGN KEY (devis_id) REFERENCES devis(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS devis_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS commande (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            devis_id INTEGER,
            user_id INTEGER,
            commande_number TEXT UNIQUE NOT NULL,
            total_amount REAL NOT NULL,
            status TEXT DEFAULT 'created',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (devis_id) REFERENCES devis(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS commande_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commande_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            line_total REAL NOT NULL,
            FOREIGN KEY (commande_id) REFERENCES commande(id)
        )
    """)

    # Insert test users
    users = [
        ("Jean Dupont", "jean.dupont@example.com", "TechCorp"),
        ("Marie Martin", "marie.martin@example.com", "InnoSoft"),
        ("Pierre Dubois", "pierre.dubois@example.com", "DataFlow"),
    ]

    cursor.executemany(
        "INSERT OR IGNORE INTO users (name, email, company) VALUES (?, ?, ?)",
        users
    )

    # Insert test stock
    stock = [
        ("Laptop Dell XPS 15", 50, 1500.00),
        ("Souris Logitech MX Master", 200, 99.99),
        ("Clavier Mécanique", 150, 149.99),
        ("Écran 27 pouces 4K", 30, 450.00),
        ("Webcam HD", 80, 79.99),
        ("Casque Audio Sony", 100, 199.99),
        ("Hub USB-C", 120, 49.99),
        ("Câble HDMI 2m", 300, 15.99),
    ]

    cursor.executemany(
        "INSERT OR IGNORE INTO stock (product_name, qty, unit_price) VALUES (?, ?, ?)",
        stock
    )

    # Insert sample devis (header)
    sample_devis = [
        (None, 1, "2024-TEST-001", 7500.00, "pending"),     # Jean: 5 Laptops
        (None, 2, "2024-TEST-002", 1999.80, "pending"),     # Marie: 20 Souris
        (None, 1, "2024-TEST-003", 4500.00, "completed"),   # Jean: 10 Écrans
    ]

    cursor.executemany(
        "INSERT OR IGNORE INTO devis (devis_raw_id, user_id, devis_number, total_amount, status) VALUES (?, ?, ?, ?, ?)",
        sample_devis
    )

    # Insert devis items (lines)
    sample_devis_items = [
        (1, "Laptop Dell XPS 15", 5, 1500.00, 7500.00),
        (2, "Souris Logitech MX Master", 20, 99.99, 1999.80),
        (3, "Écran 27 pouces 4K", 10, 450.00, 4500.00),
    ]

    cursor.executemany(
        "INSERT OR IGNORE INTO devis_items (devis_id, product_name, qty, unit_price, line_total) VALUES (?, ?, ?, ?, ?)",
        sample_devis_items
    )

    # Insert devis_raw (fichiers PDF/TXT à traiter)
    devis_raw_files = [
        ("devis_2024_001.txt", "test_data/devis_2024_001.txt", 2, "pending"),  # Marie Martin
        ("devis_2024_002.txt", "test_data/devis_2024_002.txt", 1, "pending"),  # Jean Dupont
    ]

    cursor.executemany(
        "INSERT OR IGNORE INTO devis_raw (filename, file_path, user_id, status) VALUES (?, ?, ?, ?)",
        devis_raw_files
    )

    conn.commit()

    # Display summary
    print("✅ Database initialized successfully!")
    print(f"\n📊 Summary:")
    print(f"  - Users: {cursor.execute('SELECT COUNT(*) FROM users').fetchone()[0]}")
    print(f"  - Stock items: {cursor.execute('SELECT COUNT(*) FROM stock').fetchone()[0]}")
    print(f"  - Devis: {cursor.execute('SELECT COUNT(*) FROM devis').fetchone()[0]}")
    print(f"  - Devis items: {cursor.execute('SELECT COUNT(*) FROM devis_items').fetchone()[0]}")
    print(f"  - Devis bruts (fichiers): {cursor.execute('SELECT COUNT(*) FROM devis_raw').fetchone()[0]}")
    print(f"  - Commandes: {cursor.execute('SELECT COUNT(*) FROM commande').fetchone()[0]}")
    print(f"  - Commande items: {cursor.execute('SELECT COUNT(*) FROM commande_items').fetchone()[0]}")

    print(f"\n📦 Stock disponible:")
    for row in cursor.execute("SELECT product_name, qty, unit_price FROM stock ORDER BY product_name"):
        print(f"  - {row[0]}: {row[1]} unités @ {row[2]}€")

    print(f"\n📄 Devis bruts à traiter:")
    for row in cursor.execute("SELECT id, filename, user_id, status FROM devis_raw ORDER BY id"):
        print(f"  - #{row[0]}: {row[1]} (User {row[2]}) - Status: {row[3]}")

    print(f"\n📋 Devis structurés:")
    for devis_row in cursor.execute("SELECT id, devis_number, user_id, total_amount, status FROM devis ORDER BY id"):
        print(f"  - Devis #{devis_row[0]} ({devis_row[1]}): User {devis_row[2]} - {devis_row[3]}€ - Status: {devis_row[4]}")
        # Display items for this devis
        for item_row in cursor.execute("SELECT product_name, qty, unit_price, line_total FROM devis_items WHERE devis_id = ?", (devis_row[0],)):
            print(f"      • {item_row[0]}: {item_row[1]} x {item_row[2]}€ = {item_row[3]}€")

    conn.close()


if __name__ == "__main__":
    init_database()
