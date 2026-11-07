# E-Parking v2 — Booth PC Installation Guide

> Install a minimal booth PC with the booth bridge, Chrome kiosk, and serial device support.

---

## Prerequisites

| Requirement | Minimum |
|------------|---------|
| OS | Ubuntu 24.04 LTS |
| CPU | 2 cores |
| RAM | 4 GB |
| Disk | 20 GB SSD |
| Network | Same LAN as server |
| Serial | 2-3 USB-to-Serial adapters |

### Serial Devices Needed

| Device | Typical Port | Baudrate | Purpose |
|--------|-------------|----------|---------|
| E-Money Reader | `/dev/ttyUSB0` | 38400 | PASSTI card reader |
| Receipt Printer | `/dev/ttyUSB1` | 9600 | Thermal printer |
| Barcode Scanner | `/dev/ttyUSB2` | 9600 | Ticket/barcode input |

> Use `dmesg | grep ttyUSB` after plugging devices to confirm ports.

---

## Quick Start

```bash
# 1. Copy the whole project folder to the booth PC (USB stick or scp)

# 2. On the booth PC, run the installer from the project root
cd parking-system-v2
sudo ./install.sh --booth --server-ip <server-ip> --token <enrollment-token>
```

Get the enrollment token from the server: it is printed at the end of the
server install and stored in `/etc/parking/install-notes.txt`
(regenerate: `sudo scripts/regen-enroll-token.sh`).

Without flags, the booth role script asks interactively for:
- **Server IP** — the main server PC's IP address
- **Booth name/code** — e.g. "Booth 2", "BOOTH_02"
- **Booth PC IP** — for auto-detection by the POS page
- **Default gate** — which exit gate this booth controls
- **Serial device paths** — `/dev/ttyUSB*` for each peripheral
- **Auto-login** — whether to enable automatic desktop login

---

## What Gets Installed

### System Packages
- `python3.12` — Runtime for booth bridge
- `google-chrome-stable` — Kiosk browser

### Application
- Full repo cloned to `/opt/parking-system-v2`
- Minimal Python venv with `pyserial`, `websockets`

### Configuration
- `/etc/parking/booth.json` — Booth bridge config

### Systemd Service
| Service | Purpose |
|---------|---------|
| `booth-bridge-<code>.service` | WebSocket server for serial devices (port 5678) |

### Desktop Shortcut
- `~/Desktop/Parking-POS.desktop` — Chrome kiosk pointing to server

---

## Post-Installation

### 1. Verify Serial Devices

```bash
ls -la /dev/ttyUSB*
# Expected: ttyUSB0, ttyUSB1, ttyUSB2 (or similar)
```

If device names are different, edit `/etc/parking/booth.json` and restart:
```bash
sudo systemctl restart booth-bridge-<code>
```

### 2. Verify Booth Bridge

```bash
sudo journalctl -u booth-bridge-<code> -f
# Expected: "Starting booth bridge", "Serial devices started"
```

### 3. Test WebSocket

```bash
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  http://localhost:5678/
# Expected: HTTP/1.1 101 Switching Protocols
```

### 4. Server-Side Setup (Must Be Done First)

Before this booth PC can work, the server must have:
1. Gate records created in the Device page
2. Gate daemons running (`./scripts/enable-gate-daemons.sh --run` on server)
3. This booth's POS record added

### 5. Configure POS Record on Server

Log in to the server admin page and add a POS record:

| Field | Value |
|-------|-------|
| Name | `Booth 2` |
| Code | `BOOTH_02` |
| IP Address | `192.168.1.101` (this PC's IP) |
| Gate Default | `GOUT-02` |

Then edit the corresponding gate and set its **POS** field to `BOOTH_02`.

### 6. Test Auto-Detection

1. Double-click the **Parking POS** desktop shortcut
2. Chrome opens in fullscreen kiosk mode
3. Log in as operator (not admin)
4. The gate dropdown should **auto-hide** and show the assigned gate name
5. Header should show: `Booth: Connected`

If auto-detection fails:
- Check browser console for errors
- Verify booth IP matches the POS record
- Ensure operator role is NOT admin

---

## Troubleshooting

### Booth bridge won't start
```bash
sudo journalctl -u booth-bridge-<code> -n 50
# Check: serial device paths correct? parking user in dialout group?
```

### POS says "Booth Disconnected"
```bash
# On booth PC:
sudo systemctl status booth-bridge-<code>
netstat -tlnp | grep 5678

# Test WebSocket:
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" http://localhost:5678/
```

### Serial device not found
```bash
# Re-plug and check:
dmesg | tail -20
dmesg | grep ttyUSB

# Fix permissions:
sudo usermod -aG dialout parking
# Then reboot or re-login
```

### Chrome won't open fullscreen
```bash
# Check shortcut exists and is executable:
ls -la ~/Desktop/Parking-POS.desktop
chmod +x ~/Desktop/Parking-POS.desktop

# Manually test:
google-chrome --app=http://<server-ip> --start-fullscreen --kiosk
```

### Printer not printing
```bash
# Test serial connection:
python3 -c "
import serial
s = serial.Serial('/dev/ttyUSB1', 9600, timeout=1)
print('Connected:', s.is_open)
s.write(b'\x1b\x40')  # Initialize printer
s.close()
"
```

---

## Maintenance

### Update Booth Bridge Code
```bash
cd /opt/parking-system-v2
sudo -u parking git pull origin main
sudo systemctl restart booth-bridge-<code>
```

### Change Serial Device Paths
```bash
sudo nano /etc/parking/booth.json
sudo systemctl restart booth-bridge-<code>
```

---

*Last updated: April 2026*
