#!/usr/bin/env python3
"""
Pearly - Phone-in-box focus reward system
Hardware: Pi Zero W, 1602A LCD (4-bit GPIO), reed switch, limit switch
"""

import time
import math
import sqlite3
import signal
import sys
from datetime import datetime
import RPi.GPIO as GPIO

# ── GPIO Pin Assignments (BCM) ─────────────────────────────────────────────
LCD_RS = 25
LCD_E  = 24
LCD_D4 = 23
LCD_D5 = 17
LCD_D6 = 18
LCD_D7 = 22

PIN_REED  = 12   # Reed switch: lid sensor (LOW = closed)
PIN_LIMIT = 16   # Limit switch: phone present (LOW = pressed)

# ── LCD Constants ──────────────────────────────────────────────────────────
LCD_WIDTH = 16
LCD_CHR   = True
LCD_CMD   = False
LCD_LINE1 = 0x80
LCD_LINE2 = 0xC0
E_PULSE   = 0.001
E_DELAY   = 0.001

# ── Pearl Rate Parameters ──────────────────────────────────────────────────
RATE_START      = 1.0   # pearls/min at session start
RATE_END        = 2.0   # pearls/min at RAMP_DURATION
RAMP_DURATION   = 30.0  # minutes over which rate ramps up

# ── Database ───────────────────────────────────────────────────────────────
DB_PATH = "/home/admin/pearly.db"


# ══════════════════════════════════════════════════════════════════════════
# LCD Driver
# ══════════════════════════════════════════════════════════════════════════

def lcd_init():
    GPIO.setmode(GPIO.BCM)
    for pin in (LCD_RS, LCD_E, LCD_D4, LCD_D5, LCD_D6, LCD_D7):
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, False)

    # Initialization sequence per HD44780 datasheet
    time.sleep(0.05)
    lcd_byte(0x33, LCD_CMD)
    lcd_byte(0x32, LCD_CMD)
    lcd_byte(0x28, LCD_CMD)  # 4-bit, 2 line, 5x8 dots
    lcd_byte(0x0C, LCD_CMD)  # display on, cursor off
    lcd_byte(0x06, LCD_CMD)  # entry mode: increment, no shift
    lcd_byte(0x01, LCD_CMD)  # clear display
    time.sleep(0.005)


def lcd_byte(bits, mode):
    GPIO.output(LCD_RS, mode)
    # High nibble
    GPIO.output(LCD_D4, bool(bits & 0x10))
    GPIO.output(LCD_D5, bool(bits & 0x20))
    GPIO.output(LCD_D6, bool(bits & 0x40))
    GPIO.output(LCD_D7, bool(bits & 0x80))
    lcd_toggle_enable()
    # Low nibble
    GPIO.output(LCD_D4, bool(bits & 0x01))
    GPIO.output(LCD_D5, bool(bits & 0x02))
    GPIO.output(LCD_D6, bool(bits & 0x04))
    GPIO.output(LCD_D7, bool(bits & 0x08))
    lcd_toggle_enable()


def lcd_toggle_enable():
    time.sleep(E_DELAY)
    GPIO.output(LCD_E, True)
    time.sleep(E_PULSE)
    GPIO.output(LCD_E, False)
    time.sleep(E_DELAY)


def lcd_write(line1: str, line2: str = ""):
    lcd_byte(LCD_LINE1, LCD_CMD)
    for c in line1.ljust(LCD_WIDTH)[:LCD_WIDTH]:
        lcd_byte(ord(c), LCD_CHR)
    lcd_byte(LCD_LINE2, LCD_CMD)
    for c in line2.ljust(LCD_WIDTH)[:LCD_WIDTH]:
        lcd_byte(ord(c), LCD_CHR)


# ══════════════════════════════════════════════════════════════════════════
# GPIO / Switch Setup
# ══════════════════════════════════════════════════════════════════════════

def switches_init():
    GPIO.setup(PIN_REED,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_LIMIT, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def lid_closed() -> bool:
    return GPIO.input(PIN_REED) == GPIO.LOW


def phone_present() -> bool:
    return GPIO.input(PIN_LIMIT) == GPIO.HIGH


def session_active() -> bool:
    return lid_closed() and phone_present()


# ══════════════════════════════════════════════════════════════════════════
# Database
# ══════════════════════════════════════════════════════════════════════════

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def db_init(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            ended_at    TEXT,
            duration_s  REAL,
            pearls      REAL
        );
        CREATE TABLE IF NOT EXISTS totals (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            pearls      REAL NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO totals (id, pearls) VALUES (1, 0);
    """)
    conn.commit()


def db_get_total(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT pearls FROM totals WHERE id = 1").fetchone()
    return row["pearls"] if row else 0.0


def db_save_session(conn: sqlite3.Connection, started_at: datetime,
                    duration_s: float, pearls: float):
    ended_at = datetime.now()
    conn.execute(
        "INSERT INTO sessions (started_at, ended_at, duration_s, pearls) "
        "VALUES (?, ?, ?, ?)",
        (started_at.isoformat(), ended_at.isoformat(), duration_s, pearls)
    )
    conn.execute("UPDATE totals SET pearls = pearls + ? WHERE id = 1", (pearls,))
    conn.commit()


# ══════════════════════════════════════════════════════════════════════════
# Pearl Rate Calculation
# ══════════════════════════════════════════════════════════════════════════

def pearls_for_duration(duration_s: float) -> float:
    """
    Linear ramp from RATE_START to RATE_END over RAMP_DURATION minutes.
    Integrates the rate curve over time to get total pearls.

    rate(t) = RATE_START + (RATE_END - RATE_START) * min(t, RAMP_DURATION) / RAMP_DURATION
    where t is in minutes.

    Split into ramp phase and flat phase:
      ramp  = integral from 0 to min(t, D) of (a + (b-a)*t/D) dt
      flat  = (b) * max(t - D, 0)
    """
    t = duration_s / 60.0
    a = RATE_START
    b = RATE_END
    D = RAMP_DURATION

    t_ramp = min(t, D)
    t_flat = max(t - D, 0.0)

    ramp_pearls = a * t_ramp + (b - a) * (t_ramp ** 2) / (2 * D)
    flat_pearls = b * t_flat

    return ramp_pearls + flat_pearls


def current_rate(duration_s: float) -> float:
    """Instantaneous pearls/min at this point in the session."""
    t = min(duration_s / 60.0, RAMP_DURATION)
    return RATE_START + (RATE_END - RATE_START) * t / RAMP_DURATION


# ══════════════════════════════════════════════════════════════════════════
# Display Helpers
# ══════════════════════════════════════════════════════════════════════════

def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{sec:02d}s"
    return f"{m:02d}m{sec:02d}s"


def display_idle(total_pearls: float):
    lcd_write(
        "Pearly is waiting",
        f"Total:{total_pearls:>7.1f}p"
    )


def display_session(elapsed_s: float, session_pearls: float, total_pearls: float):
    # Line 1: elapsed time + session pearls
    # Line 2: total pearls
    line1 = f"{fmt_duration(elapsed_s)} +{session_pearls:.1f}p"
    line2 = f"Total:{total_pearls:>7.1f}p"
    lcd_write(line1, line2)


def display_summary(session_pearls: float, total_pearls: float):
    lcd_write(
        f"  +{session_pearls:.1f} pearls!  ",
        f"Total:{total_pearls:>7.1f}p"
    )


# ══════════════════════════════════════════════════════════════════════════
# Main Loop
# ══════════════════════════════════════════════════════════════════════════

def main():
    conn = db_connect()
    db_init(conn)

    lcd_init()
    switches_init()

    in_session      = False
    session_start   = None
    last_display    = 0.0

    print("Pearly started.")

    def shutdown(sig, frame):
        print("\nShutting down...")
        if in_session and session_start:
            elapsed = time.monotonic() - session_start_mono
            pearls  = pearls_for_duration(elapsed)
            db_save_session(conn, session_start, elapsed, pearls)
            print(f"Session saved: {elapsed:.0f}s, {pearls:.2f} pearls")
        lcd_write("  Pearly offline", "  Goodbye!      ")
        time.sleep(2)
        lcd_byte(0x01, LCD_CMD)  # clear
        GPIO.cleanup()
        conn.close()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    session_start_mono = 0.0  # monotonic reference for elapsed time

    while True:
        active = session_active()
        now_mono = time.monotonic()

        if active and not in_session:
            # ── Session start ──
            in_session         = True
            session_start      = datetime.now()
            session_start_mono = now_mono
            last_display       = 0.0
            print(f"Session started at {session_start.isoformat()}")

        elif not active and in_session:
            # ── Session end ──
            elapsed       = now_mono - session_start_mono
            pearls        = pearls_for_duration(elapsed)
            db_save_session(conn, session_start, elapsed, pearls)
            total         = db_get_total(conn)
            in_session    = False
            print(f"Session ended: {elapsed:.0f}s, {pearls:.2f} pearls, total {total:.2f}")
            display_summary(pearls, total)
            time.sleep(3)

        elif in_session:
            # ── Session in progress: update display every second ──
            elapsed = now_mono - session_start_mono
            if now_mono - last_display >= 1.0:
                pearls = pearls_for_duration(elapsed)
                total  = db_get_total(conn)
                display_session(elapsed, pearls, total)
                last_display = now_mono

        else:
            # ── Idle ──
            if now_mono - last_display >= 5.0:
                total = db_get_total(conn)
                display_idle(total)
                last_display = now_mono

        time.sleep(0.1)


if __name__ == "__main__":
    main()