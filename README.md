# Pearly

Pearly is a focus-reward device. The user places their phone in the box and closes the lid. While the phone is inside and the lid is closed, the user earns pearls at a milestone-based accelerating rate. Pearls are redeemed for rewards (e.g. LEGO sets).

**Hardware:** Raspberry Pi Zero W, 1602A 16x2 LCD (CFAH1602B-TMI-JT, 4-bit GPIO mode), reed switch (lid), limit switch (phone presence).

---

## 1. Setup

### Local Computer (Windows)

**Requirements:**
- OpenSSH (built into Windows 10/11)
- Python 3 (for running `redeem.py` locally against a copied database — no extra packages needed)
- DB Browser for SQLite (optional, for visual database inspection — https://sqlitebrowser.org)
- Linux Reader by DiskInternals (optional, for reading ext4 SD card partition on Windows — https://www.diskinternals.com/linux-reader)

**SSH key setup (one time):**

Generate a key pair if you don't have one:
```powershell
ssh-keygen -t ed25519 -C "pearly"
```

Print your public key:
```powershell
cat $env:USERPROFILE\.ssh\id_ed25519.pub
```

Then on Pearly via SSH, paste the key:
```bash
ssh admin@192.168.0.56
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "paste-your-public-key-here" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

If the host key changes after a reflash:
```powershell
ssh-keygen -R 192.168.0.56
```



### Pearly (Raspberry Pi Zero W)

**OS:** Raspberry Pi OS Lite (64-bit recommended)

**During Raspberry Pi Imager setup:**
- Set hostname: `pearly`
- Set username: `admin`
- Set password
- Configure Wi-Fi (SSID and password are case-sensitive)
- Enable SSH

> Note: After a reflash, verify the Wi-Fi config at `/boot/firmware/50-cloud-init.yaml` on the FAT32 boot partition. The SSID must exactly match your network name.

**Install dependencies (once on the Pi):**
```bash
sudo apt update
sudo apt install python3-rpi.gpio sqlite3
```

**Copy app files to the Pi:**
```powershell
scp .\pearly_app.py admin@pearly.local:~/
scp .\redeem.py admin@pearly.local:~/
```

**Set up autostart via systemd:**

Create the service file:
```bash
sudo nano /etc/systemd/system/pearly.service
```

Paste:
```ini
[Unit]
Description=Pearly App
DefaultDependencies=no
After=local-fs.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin
ExecStart=/usr/bin/python3 /home/admin/pearly_app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable pearly
sudo systemctl start pearly
```

**Reduce boot time:**
```bash
sudo raspi-config
# System Options → Network at Boot → No
```

Disable unnecessary services:
```bash
sudo systemctl disable bluetooth
sudo systemctl disable avahi-daemon
sudo systemctl disable triggerhappy
```

If Pi Connect is installed and not needed, disable it — it competes for the Wi-Fi radio:
```bash
sudo systemctl disable rpi-connect
sudo systemctl stop rpi-connect
```

**SD card hardening (do last, after everything is working):**

Edit `/etc/fstab`:
```bash
sudo nano /etc/fstab
```

Add `noatime` to the root (`/`) mount options, then append:
```
tmpfs  /tmp      tmpfs  defaults,noatime,nosuid,size=32m   0  0
tmpfs  /var/log  tmpfs  defaults,noatime,nosuid,mode=0755  0  0
tmpfs  /var/tmp  tmpfs  defaults,noatime,nosuid,size=16m   0  0
```

This reduces unnecessary writes. The database at `~/pearly.db` remains on the writable root partition and persists normally.

---

### Pin Wiring Reference

**LCD (CFAH1602B-TMI-JT, 4-bit mode)**

| LCD Pin | Signal  | BCM GPIO | Physical Pin |
|---------|---------|----------|--------------|
| 4       | RS      | 25       | 22           |
| 6       | E       | 24       | 18           |
| 11      | D4      | 23       | 16           |
| 12      | D5      | 17       | 11           |
| 13      | D6      | 18       | 12           |
| 14      | D7      | 22       | 15           |
| 1       | GND     | —        | Any GND      |
| 2       | VCC     | —        | 5V (Pin 2/4) |
| 3       | V0      | —        | Contrast resistor to GND |
| 5       | RW      | —        | GND          |
| 15      | A (BL+) | —        | 5V or via resistor |
| 16      | K (BL-) | —        | GND          |

**Switches**

| Switch        | BCM GPIO | Physical Pin | Logic          |
|---------------|----------|--------------|----------------|
| Reed (lid)    | 12       | 32           | LOW = closed   |
| Limit (phone) | 16       | 36           | HIGH = present |

Both switches use the Pi's internal pull-up resistors. No external resistors needed.

---

## 2. Pearl Accumulation

Pearls accumulate in whole numbers at a milestone-based rate during a session. A session begins when both the lid is closed and the phone is present. It ends when either condition is broken.

| Elapsed Time | Rate         |
|--------------|--------------|
| 0–15 min     | 5 pearls/min |
| 15–30 min    | 8 pearls/min |
| 30 min+      | 10 pearls/min |

Progress is checkpointed to the database every 5 minutes during a session so power loss doesn't wipe the whole session.

---

## 3. Local Computer Commands

**SSH into Pearly:**
```powershell
ssh admin@192.168.0.56
```

**Push updated app file:**
```powershell
scp .\pearly_app.py admin@192.168.0.56:~/
```

**Push redemption tool:**
```powershell
scp .\redeem.py admin@192.168.0.56:~/
```

**Restart the app after pushing changes:**
```bash
sudo systemctl restart pearly
```

**Check app status / live logs:**
```bash
sudo systemctl status pearly
journalctl -u pearly -f
```

**Stop / start the service:**
```bash
sudo systemctl stop pearly
sudo systemctl start pearly
```

**Run the app manually (service must be stopped first):**
```bash
sudo python3 pearly_app.py
```

---

## 4. Pearl Redemption & Bonuses

### Option A: redeem.py on Pearly via SSH (recommended)

```bash
# Check balance
python3 redeem.py --balance

# Redeem pearls
python3 redeem.py 500 "LEGO Botanical Rose"

# Credit bonus pearls
python3 redeem.py --bonus 100 "Good behavior"

# View history (shows both redemptions and bonuses)
python3 redeem.py --history
```

Redemptions are refused if the balance would go below zero. All transactions are logged to the `redemptions` table with timestamp and reason.

---

### Option B: redeem.py from Windows via SD card (offline / SSH unreliable)

Use this when SSH is unavailable. Requires Python 3 installed on Windows.

**Step 1 — Pull the database off the SD card:**

The database lives on the ext4 root partition (not the FAT32 boot partition). Use **Linux Reader** (DiskInternals) to navigate to `/home/admin/pearly.db` and extract it to your desktop.

**Step 2 — Run redeem.py locally:**
```powershell
python redeem.py --db C:\Users\mstel\Desktop\pearly.db --balance
python redeem.py --db C:\Users\mstel\Desktop\pearly.db 500 "LEGO Botanical Rose"
python redeem.py --db C:\Users\mstel\Desktop\pearly.db --bonus 100 "Good behavior"
python redeem.py --db C:\Users\mstel\Desktop\pearly.db --history
```

**Step 3 — Write the database back:**

Use Linux Reader's write mode or Ext2Fsd to copy the edited `pearly.db` back to `/home/admin/pearly.db` on the ext4 partition. Eject safely before reinserting the SD card.

> ⚠️ Do not edit the database while `pearly_app.py` is running. Stop the service first or pull the SD card with the Pi powered off.

---

### Option C: Direct SQLite access on Pearly

For inspection or emergency edits via SSH:
```bash
sqlite3 ~/pearly.db
```

```sql
-- Check balance
SELECT pearls FROM totals WHERE id = 1;

-- View session history (id = -1 is the live checkpoint if a session is running)
SELECT id, started_at, ended_at, duration_s, pearls FROM sessions ORDER BY started_at DESC LIMIT 10;

-- View redemption/bonus history (negative amounts = bonuses)
SELECT redeemed_at, amount, reason FROM redemptions ORDER BY redeemed_at DESC;

-- Exit
.quit
```

> ⚠️ Direct SQL edits bypass the redemption log. Prefer `redeem.py` so there's a full audit trail.