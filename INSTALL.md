# E-Parking v2 — Step-by-Step Installation

This guide is for the person installing the system at the site. You do **not**
need to know programming. Copy the lines in the grey boxes into a terminal,
press Enter, and follow the screens.

**Words used in this guide**

| Word | Meaning |
|---|---|
| Server PC | The computer that runs the parking system (database + web page). Keep it on 24/7. |
| Booth PC | Optional computer at an exit gate, connected to the card reader / printer. |
| Terminal | The black window where you type commands. On Ubuntu press `Ctrl` + `Alt` + `T`. |
| Ubuntu | The operating system on the Server PC. |

---

## 1. Check the Server PC (2 minutes)

You need:

- Ubuntu **24.04 LTS** installed (not 22.04 — the install will fail).
- At least 2 GB RAM and 5 GB free disk (4 GB RAM / 10 GB disk recommended).
- Internet connection during installation.
- The Server PC's IP address.

Run these two lines in a terminal and write the answers down:

```bash
lsb_release -ds
hostname -I
```

Expected:

- First line starts with `Ubuntu 24.04`.
- Second line shows a number like `192.168.1.10`. That is the **Server IP**.

> If the first line is not Ubuntu 24.04, stop and reinstall Ubuntu 24.04 first.

---

## 2. Put the program on the Server PC

**Option A — USB stick (recommended, no internet needed for the code):**

1. Copy the whole `parking-system-v2` folder onto a USB stick.
2. Plug it into the Server PC and copy the folder into the home folder.
3. Open a terminal and enter the folder:

```bash
cd ~/parking-system-v2
ls install.sh
```

You must see `install.sh` in the output.

**Option B — download from GitHub:**

```bash
cd ~
git clone <repository-url> parking-system-v2
cd parking-system-v2
```

> Do not install from `installer/` and do not run files inside `installer/_roles/`.
> Only `install.sh` is used.

---

## 3. Install (one command)

```bash
sudo ./install.sh
```

What happens:

1. Ubuntu asks for **your** login password. While you type it, nothing appears
   on screen — that is normal. Press Enter.
2. The installer prints steps `0/12` to `12/12`. This takes several minutes.
   Do not close the window. It needs internet: it updates Ubuntu packages and
   downloads the application dependencies.
3. It sets the system timezone to **Asia/Jakarta**, installs PostgreSQL, Redis,
   nginx, creates the `parking` system user, the database, and the services.
4. At the end you see either:

```
  Server installation complete!
  Open in a browser:  http://<server-ip>/        (operator/admin page)
  Username  : admin
  Password  : sudo cat /etc/parking/install-notes.txt  (mode 0600)
```

or an error telling you exactly which check failed.

### Optional settings

| What you want | Command |
|---|---|
| Use the defaults | `sudo ./install.sh` |
| Set site name / gate count / tariff | `sudo ./install.sh --site-name "Parkir RS Example" --topology 2in2out --tariff mall` |
| Choose everything in a browser wizard | `sudo ./install.sh --advanced` |
| Install a booth PC | `sudo ./install.sh --booth --server-ip <server-ip> --token <enrollment-token>` |

Valid `--topology` values: `1in1out`, `1in2out`, `2in2out`, `NinMout`.
Valid `--tariff` values: `standard`, `mall`.

---

## 4. Verify the installation

The installer already runs a health check and refuses to finish on failure.
To run it again at any time:

```bash
sudo parking-doctor --infra-only
```

Every row must say `PASS`. If a row says `FAIL`, fix what the row describes and
run the command again. (Full report without `--infra-only` also checks gates,
cameras and serial devices.)

---

## 5. Log in

1. On any computer in the same network, open a browser.
2. Go to `http://<server-ip>/` — for example `http://192.168.1.10/`.
3. Username: `admin` (quick mode).
4. Password: read it with this command on the Server PC:

```bash
sudo cat /etc/parking/install-notes.txt
```

Look for the line `Admin password : ...`.

Change the password after the first login.

> **Advanced mode:** there is no `install-notes.txt` password — the wizard
> created the admin account, so log in with the username/password you chose
> there. The setup link token is in `/etc/parking/setup-token`.

---

## 6. Tell the system about your gates

A quick install creates the gates you asked for (`--topology`); an advanced
install creates them in the wizard. Either way, each gate must point at its
real controller.

1. In the browser: **Device → Gates**.
2. For each lane, set the controller IP/port (TCP) or the serial device.
3. Press **Test buka/tutup** and watch the real gate. It must open and close.
4. Enable the entry-gate background services:

```bash
sudo /opt/parking-system-v2/scripts/enable-gate-daemons.sh --run
sudo systemctl status 'parking-daemon-gate-*'
```

> Exit lanes do not use a daemon. They are driven by the Booth PC.

> **Quick installs** create the gates with placeholder controller IPs starting
> at `192.168.1.100`. Until you enter the real IP/port, the gate daemons stay
> offline — that is expected, and `sudo parking-doctor --infra-only` still passes.

---

## 7. Booth PCs (only sites with exit booths)

The Server PC prints an **Enrollment token** at the end of installation, and it
is also stored in `/etc/parking/install-notes.txt`.

On each Booth PC:

```bash
cd ~/parking-system-v2
sudo ./install.sh --booth --server-ip <server-ip> --token <enrollment-token>
```

If the token expired (24 hours), generate a new one on the Server PC:

```bash
sudo /opt/parking-system-v2/scripts/regen-enroll-token.sh
```

---

## Everyday commands (on the Server PC)

```bash
# Are the services running?
systemctl status parking-api parking-worker-critical parking-worker-bg

# Restart the system
sudo systemctl restart parking-api parking-worker-critical parking-worker-bg

# Live logs
sudo journalctl -u parking-api -f

# Backups (run automatically every night at 01:00)
ls -lh /var/lib/parking-backups

# Full health report
sudo -u parking /opt/parking-system-v2/.venv/bin/python \
  /opt/parking-system-v2/scripts/parking_doctor.py
```

---

## Updating to a newer version (or repairing an install)

The same command does both — it never deletes data, passwords or the database.

1. Get the newer `parking-system-v2` folder (new USB copy or `git pull`).
2. Run the installer again:

```bash
cd parking-system-v2
sudo ./install.sh
```

What is kept: database, transactions, settings, `JWT_SECRET`, `INTERNAL_API_KEY`,
admin password, `.env` values you added (Telegram, settlement).
What is replaced: application code, Python dependencies, frontend build,
systemd units, nginx config.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `This script must be run as root` | You forgot `sudo`. Run `sudo ./install.sh`. |
| `Ubuntu 24.04` warning | The Server PC has the wrong Ubuntu. Reinstall 24.04. |
| Installer stops with `INSTALL FAILED VERIFICATION` | Read the `FAIL` rows above, fix them, then re-run the health command from step 4. |
| Browser shows "site cannot be reached" | Check the Server PC is on and run `systemctl status nginx parking-api`. |
| Login page opens but password is rejected | Read the password again: `sudo cat /etc/parking/install-notes.txt`. |
| Gate does not open from the web page | Check the controller IP/port in **Device → Gates**, then `systemctl status 'parking-daemon-gate-*'`. |
| Gate shows "offline" after install | Expected on a quick install until you set the real controller IP/port. |
| `parking-doctor: command not found` | The install did not finish; use the full path `/opt/parking-system-v2/.venv/bin/python /opt/parking-system-v2/scripts/parking_doctor.py --infra-only`. |
| Nothing works after a power cut | Wait 2 minutes, then run `sudo parking-doctor --infra-only`. |

Full troubleshooting: `installer/README.md` → *Troubleshooting*.
Advanced field guide: `docs/FIELD_TECH_GUIDE.md`.

---

## What **not** to do

- Do not install on Ubuntu 22.04 or on Windows.
- Do not run the installer from inside `installer/`.
- Do not edit `.env` by hand after installation; re-run `sudo ./install.sh`
  instead — it keeps existing secrets and data.
- Do not use the Docker path for a customer site (it is for development).
