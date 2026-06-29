#!/usr/bin/env python3
"""
Pearly - Phone-in-box focus reward system
Hardware: Pi Zero W, 1602A LCD (4-bit GPIO), reed switch, limit switch
"""

import time
import sqlite3
import signal
import sys
import random
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
PIN_LIMIT = 16   # Limit switch: phone present (HIGH = pressed)

# ── LCD Constants ──────────────────────────────────────────────────────────
LCD_WIDTH = 16
LCD_CHR   = True
LCD_CMD   = False
LCD_LINE1 = 0x80
LCD_LINE2 = 0xC0
E_PULSE   = 0.0005
E_DELAY   = 0.0005

# ── Custom Character Slots ─────────────────────────────────────────────────
CHAR_PEARL = 0   # Pearl icon slot

# ── Pearl Rate Milestones ──────────────────────────────────────────────────
# (minimum elapsed minutes, rate in pearls/min)
MILESTONES = [
    (0,   5),
    (15,  8),
    (30, 10),
]

MILESTONE_MESSAGES = [
    (15, "15 min! Rate up!"),
    (30, "30 min! Max rate!"),
    (60, "1 hour! Amazing!"),
    (120,"2 hours! Wow!   "),
]

# ── Idle Easter Eggs ───────────────────────────────────────────────────────
IDLE_SECRET_MESSAGES = [
    "Lego Lego Lego! ",
    "I see your texts",
    "Pearly is hungry",
]
IDLE_SECRET_CHANCE = 100   # 1 in N chance of showing a secret message

# ── Periodic DB Checkpoint ─────────────────────────────────────────────────
DB_CHECKPOINT_INTERVAL = 300   # seconds (5 minutes)

# ── Database ───────────────────────────────────────────────────────────────
DB_PATH = "/home/admin/pearly.db"


# ══════════════════════════════════════════════════════════════════════════
# LCD Driver
# ══════════════════════════════════════════════════════════════════════════

def lcd_init():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    for pin in (LCD_RS, LCD_E, LCD_D4, LCD_D5, LCD_D6, LCD_D7):
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, False)

    time.sleep(0.05)
    lcd_byte(0x33, LCD_CMD)
    lcd_byte(0x32, LCD_CMD)
    lcd_byte(0x28, LCD_CMD)  # 4-bit, 2 line, 5x8 dots
    lcd_byte(0x0C, LCD_CMD)  # display on, cursor off
    lcd_byte(0x06, LCD_CMD)  # entry mode
    lcd_byte(0x01, LCD_CMD)  # clear
    time.sleep(0.005)
    lcd_create_chars()


def lcd_byte(bits, mode):
    GPIO.output(LCD_RS, mode)
    GPIO.output(LCD_D4, bool(bits & 0x10))
    GPIO.output(LCD_D5, bool(bits & 0x20))
    GPIO.output(LCD_D6, bool(bits & 0x40))
    GPIO.output(LCD_D7, bool(bits & 0x80))
    lcd_toggle_enable()
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


def lcd_create_chars():
    # Pearl icon: small sphere with shine arc in top-left
    # Each row is a 5-bit pattern (bits 4-0 = columns left-right)
    pearl = [
        0b00000,   # .....
        0b00000,   # .....
        0b01110,   # .XXX.   top of sphere
        0b11111,   # XXXXX
        0b11111,   # XXXXX
        0b11111,   # XXXXX
        0b01110,   # .XXX.   bottom
        0b00000,   # .....
    ]
    # Write to CGRAM slot 0
    lcd_byte(0x40 | (CHAR_PEARL << 3), LCD_CMD)
    for row in pearl:
        lcd_byte(row, LCD_CHR)
    # Return to DDRAM
    lcd_byte(LCD_LINE1, LCD_CMD)


def lcd_write(line1: str, line2: str = ""):
    """Write two lines. Use \x00 for pearl icon character."""
    lcd_byte(LCD_LINE1, LCD_CMD)
    _lcd_write_line(line1)
    lcd_byte(LCD_LINE2, LCD_CMD)
    _lcd_write_line(line2)


def _lcd_write_line(text: str):
    text = text.ljust(LCD_WIDTH)[:LCD_WIDTH]
    for c in text:
        if c == '\x00':
            lcd_byte(CHAR_PEARL, LCD_CHR)
        else:
            lcd_byte(ord(c), LCD_CHR)


# ══════════════════════════════════════════════════════════════════════════
# Splash Screen
# ══════════════════════════════════════════════════════════════════════════

def lcd_splash():
    """
    Animate 'Welcome to' sliding in from left (starts fully off-screen),
    'Pearly' sliding in from right (starts fully off-screen).
    Both stop at their centered positions.
    """
    top    = "Welcome to"
    bottom = "Pearly"
 
    top_final    = (LCD_WIDTH - len(top))    // 2  # 3
    bottom_final = (LCD_WIDTH - len(bottom)) // 2  # 5
 
    # Top travels from -len(top) to top_final
    # Bottom travels from LCD_WIDTH to bottom_final
    steps = max(top_final + len(top), LCD_WIDTH - bottom_final) + 1
 
    for i in range(steps):
        t = i / max(steps - 1, 1)  # 0.0 → 1.0
 
        # Top: interpolate position from -len(top) to top_final
        top_pos = int(-len(top) + (top_final + len(top)) * t)
        if top_pos < 0:
            # Partially off-screen left: clip leading characters
            line1 = (top[abs(top_pos):]).ljust(LCD_WIDTH)[:LCD_WIDTH]
        else:
            line1 = (" " * top_pos + top).ljust(LCD_WIDTH)[:LCD_WIDTH]
 
        # Bottom: interpolate position from LCD_WIDTH to bottom_final
        bottom_pos = int(LCD_WIDTH - (LCD_WIDTH - bottom_final) * t)
        if bottom_pos + len(bottom) > LCD_WIDTH:
            # Partially off-screen right: clip trailing characters
            visible = max(0, LCD_WIDTH - bottom_pos)
            line2 = (" " * bottom_pos + bottom[:visible]).ljust(LCD_WIDTH)[:LCD_WIDTH]
        else:
            line2 = (" " * bottom_pos + bottom).ljust(LCD_WIDTH)[:LCD_WIDTH]
 
        lcd_write(line1, line2)
        time.sleep(0.06)
 
    # Ensure final frame is exactly centered
    lcd_write(
        top.center(LCD_WIDTH),
        bottom.center(LCD_WIDTH)
    )
    time.sleep(2.0)



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
            pearls      INTEGER
        );
        CREATE TABLE IF NOT EXISTS totals (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            pearls      INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO totals (id, pearls) VALUES (1, 0);
    """)
    conn.commit()


def db_get_total(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT pearls FROM totals WHERE id = 1").fetchone()
    return row["pearls"] if row else 0


def db_save_session(conn: sqlite3.Connection, started_at: datetime,
                    duration_s: float, pearls: int):
    ended_at = datetime.now()
    conn.execute(
        "INSERT INTO sessions (started_at, ended_at, duration_s, pearls) "
        "VALUES (?, ?, ?, ?)",
        (started_at.isoformat(), ended_at.isoformat(), duration_s, pearls)
    )
    conn.execute("UPDATE totals SET pearls = pearls + ? WHERE id = 1", (pearls,))
    conn.commit()


def db_checkpoint(conn: sqlite3.Connection, started_at: datetime,
                  duration_s: float, pearls: int):
    """
    Upsert a running session record so progress is preserved on power loss.
    Uses a fixed id of -1 to distinguish from completed sessions.
    On session end, db_save_session writes the real record and this is deleted.
    """
    conn.execute("""
        INSERT INTO sessions (id, started_at, ended_at, duration_s, pearls)
        VALUES (-1, ?, 'IN PROGRESS', ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            ended_at   = 'IN PROGRESS',
            duration_s = excluded.duration_s,
            pearls     = excluded.pearls
    """, (started_at.isoformat(), duration_s, pearls))
    conn.commit()
    print(f"Checkpoint saved: {duration_s:.0f}s, {pearls} pearls")


# ══════════════════════════════════════════════════════════════════════════
# Pearl Rate Calculation
# ══════════════════════════════════════════════════════════════════════════

def current_rate(elapsed_s: float) -> int:
    """Return current pearls/min based on milestone thresholds."""
    elapsed_min = elapsed_s / 60.0
    rate = MILESTONES[0][1]
    for min_elapsed, milestone_rate in MILESTONES:
        if elapsed_min >= min_elapsed:
            rate = milestone_rate
    return rate


def pearls_for_duration(duration_s: float) -> int:
    """
    Compute total pearls earned by integrating milestone-based rates.
    Returns a whole number.
    """
    total = 0.0
    duration_min = duration_s / 60.0

    # Build milestone breakpoints in minutes
    breakpoints = [(m, r) for m, r in MILESTONES]

    for i, (start_min, rate) in enumerate(breakpoints):
        end_min = breakpoints[i + 1][0] if i + 1 < len(breakpoints) else duration_min
        end_min = min(end_min, duration_min)
        if start_min >= duration_min:
            break
        segment = end_min - start_min
        total += segment * rate

    return int(total)


def next_milestone_min(elapsed_s: float):
    """Return the next milestone in minutes, or None if past all milestones."""
    elapsed_min = elapsed_s / 60.0
    for min_elapsed, _ in MILESTONES:
        if elapsed_min < min_elapsed:
            return min_elapsed
    return None


# ══════════════════════════════════════════════════════════════════════════
# Display Helpers
# ══════════════════════════════════════════════════════════════════════════

def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m:02d}m{sec:02d}s"


def pick_idle_content():
    """Choose idle screen content once."""
    if random.randint(1, IDLE_SECRET_CHANCE) == 1:
        return random.choice(IDLE_SECRET_MESSAGES)
    return "Pearly is ready "


def display_idle(line1: str, total: int):
    lcd_write(line1, f"Total: {total}\x00")


def display_session(elapsed_s: float, session_pearls: int, total: int):
    # Line 1: elapsed time + session pearls with icon
    # Line 2: rate with icon + next milestone countdown
    rate = current_rate(elapsed_s)
    next_ms = next_milestone_min(elapsed_s)

    time_str = fmt_duration(elapsed_s)
    line1 = f"{time_str} +{session_pearls}\x00"

    if next_ms is not None:
        remaining = int(next_ms - elapsed_s / 60.0) + 1
        line2 = f"Rate:{rate}\x00/m +{remaining}m"
    else:
        line2 = f"Rate:{rate}\x00/m MAX!"

    lcd_write(line1, line2)


def display_milestone(message: str, session_pearls: int):
    lcd_write(
        message,
        f"+{session_pearls}\x00 this session"
    )


def display_summary(session_pearls: int, total: int):
    if session_pearls == 0:
        line1 = f"{session_pearls}\x00 earned, oof  "
    else:
        line1 = f"+{session_pearls}\x00 earned!  "
    lcd_write(line1, f"Total: {total}\x00")


# ══════════════════════════════════════════════════════════════════════════
# Main Loop
# ══════════════════════════════════════════════════════════════════════════

def main():
    conn = db_connect()
    db_init(conn)

    lcd_init()
    switches_init()

    lcd_splash()

    in_session         = False
    session_start      = None
    session_start_mono = 0.0
    last_display       = 0.0
    last_milestone_min = -1  # track which milestones we've shown
    milestone_show_until = 0.0  # monotonic time until which to show milestone msg
    last_checkpoint    = 0.0  # monotonic time of last DB checkpoint
    idle_content       = pick_idle_content()  # chosen once per idle screen showing

    print("Pearly started.")

    def shutdown(sig, frame):
        print("\nShutting down...")
        if in_session and session_start:
            elapsed = time.monotonic() - session_start_mono
            pearls  = pearls_for_duration(elapsed)
            conn.execute("DELETE FROM sessions WHERE id = -1")
            conn.commit()
            db_save_session(conn, session_start, elapsed, pearls)
            print(f"Session saved: {elapsed:.0f}s, {pearls} pearls")
        lcd_write(" Pearly offline ", "  Buh bye now!  ")
        time.sleep(2)
        lcd_byte(0x01, LCD_CMD)
        GPIO.cleanup()
        conn.close()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while True:
        active   = session_active()
        now_mono = time.monotonic()

        if active and not in_session:
            # ── Session start ──
            in_session         = True
            session_start      = datetime.now()
            session_start_mono = now_mono
            last_display       = 0.0
            last_milestone_min = -1
            milestone_show_until = 0.0
            last_checkpoint    = now_mono
            idle_content       = pick_idle_content()
            print(f"Session started at {session_start.isoformat()}")

        elif not active and in_session:
            # ── Session end ──
            elapsed = now_mono - session_start_mono
            pearls  = pearls_for_duration(elapsed)
            # Remove checkpoint record before writing final session
            conn.execute("DELETE FROM sessions WHERE id = -1")
            conn.commit()
            db_save_session(conn, session_start, elapsed, pearls)
            total   = db_get_total(conn)
            in_session = False
            print(f"Session ended: {elapsed:.0f}s, {pearls} pearls, total {total}")
            display_summary(pearls, total)
            time.sleep(4)

        elif in_session:
            elapsed = now_mono - session_start_mono
            elapsed_min = elapsed / 60.0

            # Periodic checkpoint every 5 minutes
            if now_mono - last_checkpoint >= DB_CHECKPOINT_INTERVAL:
                db_checkpoint(conn, session_start, elapsed, pearls_for_duration(elapsed))
                last_checkpoint = now_mono

            # Check for milestone messages
            for ms_min, ms_msg in MILESTONE_MESSAGES:
                if elapsed_min >= ms_min and last_milestone_min < ms_min:
                    last_milestone_min = ms_min
                    milestone_show_until = now_mono + 3.0
                    display_milestone(ms_msg, pearls_for_duration(elapsed))
                    break

            # Update display every second, unless showing milestone
            if now_mono - last_display >= 1.0 and now_mono >= milestone_show_until:
                pearls = pearls_for_duration(elapsed)
                total  = db_get_total(conn)
                display_session(elapsed, pearls, total)
                last_display = now_mono

        else:
            # ── Idle ──
            if now_mono - last_display >= 5.0:
                total = db_get_total(conn)
                display_idle(idle_content, total)
                last_display = now_mono

        time.sleep(0.1)


if __name__ == "__main__":
    main()