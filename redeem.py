#!/usr/bin/env python3
"""
Pearly - Pearl Redemption Tool

On Pearly via SSH:
  python3 redeem.py --balance
  python3 redeem.py 500 "LEGO Botanical Rose"
  python3 redeem.py --history

From local Windows machine (SD card copied database):
  python redeem.py --db C:\path\to\pearly.db --balance
  python redeem.py --db C:\path\to\pearly.db 500 "LEGO Botanical Rose"
"""

import sqlite3
import sys
from datetime import datetime

DEFAULT_DB_PATH = "/home/admin/pearly.db"


def db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def db_init(conn: sqlite3.Connection):
    """Ensure redemptions table exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS redemptions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            redeemed_at TEXT NOT NULL,
            amount      INTEGER NOT NULL,
            reason      TEXT
        )
    """)
    conn.commit()


def get_balance(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT pearls FROM totals WHERE id = 1").fetchone()
    return row["pearls"] if row else 0


def redeem(conn: sqlite3.Connection, amount: int, reason: str = None):
    balance = get_balance(conn)

    if amount <= 0:
        print(f"Error: amount must be a positive integer.")
        sys.exit(1)

    if amount > balance:
        print(f"Error: not enough pearls. Balance is {balance}, tried to redeem {amount}.")
        sys.exit(1)

    conn.execute("UPDATE totals SET pearls = pearls - ? WHERE id = 1", (amount,))
    conn.execute(
        "INSERT INTO redemptions (redeemed_at, amount, reason) VALUES (?, ?, ?)",
        (datetime.now().isoformat(), amount, reason)
    )
    conn.commit()

    new_balance = get_balance(conn)
    reason_str = f" for \"{reason}\"" if reason else ""
    print(f"Redeemed {amount} pearls{reason_str}.")
    print(f"New balance: {new_balance} pearls.")


def bonus(conn: sqlite3.Connection, amount: int, reason: str = None):
    if amount <= 0:
        print(f"Error: amount must be a positive integer.")
        sys.exit(1)

    conn.execute("UPDATE totals SET pearls = pearls + ? WHERE id = 1", (amount,))
    conn.execute(
        "INSERT INTO redemptions (redeemed_at, amount, reason) VALUES (?, ?, ?)",
        (datetime.now().isoformat(), -amount, f"BONUS: {reason}" if reason else "BONUS")
    )
    conn.commit()

    new_balance = get_balance(conn)
    reason_str = f" for \"{reason}\"" if reason else ""
    print(f"Credited {amount} bonus pearls{reason_str}.")
    print(f"New balance: {new_balance} pearls.")


def print_history(conn: sqlite3.Connection):
    rows = conn.execute(
        "SELECT redeemed_at, amount, reason FROM redemptions ORDER BY redeemed_at DESC LIMIT 10"
    ).fetchall()
    if not rows:
        print("No history yet.")
        return
    print(f"{'Date':<22} {'Amount':>7}  Reason")
    print("-" * 55)
    for r in rows:
        date = r["redeemed_at"][:16].replace("T", " ")
        reason = r["reason"] or ""
        amount = r["amount"]
        # Negative amounts in the table = bonus credits
        if amount < 0:
            label = f"+{abs(amount):>5} (bonus)"
        else:
            label = f"-{amount:>5}        "
        print(f"{date:<22} {label}  {reason}")


def usage():
    print("Usage:")
    print("  python3 redeem.py [--db <path>] --balance")
    print("  python3 redeem.py [--db <path>] --history")
    print("  python3 redeem.py [--db <path>] <amount>")
    print("  python3 redeem.py [--db <path>] <amount> \"reason\"")
    print("  python3 redeem.py [--db <path>] --bonus <amount>")
    print("  python3 redeem.py [--db <path>] --bonus <amount> \"reason\"")
    print()
    print("  --db <path>   Path to pearly.db (default: /home/admin/pearly.db)")
    print("                Omit when running on Pearly via SSH.")
    print("                Required when running on Windows against a copied database.")
    print("  --bonus       Credit bonus pearls instead of redeeming.")
    print()
    print("Examples (on Pearly via SSH):")
    print("  python3 redeem.py --balance")
    print("  python3 redeem.py 500 \"LEGO Botanical Rose\"")
    print("  python3 redeem.py --bonus 100 \"Good behavior\"")
    print()
    print("Examples (Windows, SD card database):")
    print("  python redeem.py --db C:\\Users\\mstel\\Desktop\\pearly.db --balance")
    print("  python redeem.py --db C:\\Users\\mstel\\Desktop\\pearly.db 500 \"LEGO Rose\"")
    print("  python redeem.py --db C:\\Users\\mstel\\Desktop\\pearly.db --bonus 100 \"Bonus\"")


if __name__ == "__main__":
    args = sys.argv[1:]

    # Parse optional --db flag
    db_path = DEFAULT_DB_PATH
    if "--db" in args:
        idx = args.index("--db")
        if idx + 1 >= len(args):
            print("Error: --db requires a path argument.")
            sys.exit(1)
        db_path = args[idx + 1]
        args = args[:idx] + args[idx + 2:]  # remove --db and its value

    if not args:
        usage()
        sys.exit(0)

    try:
        conn = db_connect(db_path)
    except Exception as e:
        print(f"Error: could not open database at '{db_path}'.")
        print(f"  {e}")
        sys.exit(1)

    db_init(conn)

    arg = args[0]

    if arg in ("--balance", "-b"):
        balance = get_balance(conn)
        print(f"Current balance: {balance} pearls.")

    elif arg in ("--history", "-h"):
        print_history(conn)

    elif arg in ("--bonus",):
        if len(args) < 2:
            print("Error: --bonus requires an amount.")
            usage()
            sys.exit(1)
        try:
            amount = int(args[1])
        except ValueError:
            print(f"Error: '{args[1]}' is not a valid amount.")
            sys.exit(1)
        reason = args[2] if len(args) >= 3 else None
        bonus(conn, amount, reason)

    else:
        try:
            amount = int(arg)
        except ValueError:
            print(f"Error: '{arg}' is not a valid amount.")
            usage()
            sys.exit(1)

        reason = args[1] if len(args) >= 2 else None
        redeem(conn, amount, reason)

    conn.close()