# E-Parking v2 Installer

**Technicians run `install.sh` from the repository root — not this directory.**
Step-by-step guide for non-technical installers: [`../INSTALL.md`](../INSTALL.md).

```bash
cd parking-system-v2
sudo ./install.sh              # server, quick defaults (no questions)
sudo ./install.sh --advanced   # server, guided browser setup wizard
sudo ./install.sh --booth --server-ip <server-ip> --token <enroll-token>
sudo ./install.sh --combo      # server + on-box booth (single-PC site)
```

`install.sh` forwards to `setup.sh` in this directory (adding `--quick` unless
`--advanced`). Call `setup.sh` directly only when debugging the installer.

```bash
# Unattended (CI / scripted field rolls). Non-interactive requires a role;
# booth configure additionally needs server IP + enrollment token:
sudo ./setup.sh --role server --non-interactive
sudo ./setup.sh --role booth --non-interactive \
    --server-ip=192.168.1.100 --token=<enroll-token> \
    --booth-code=BOOTH_02 --gate-code=GOUT-02
sudo ./setup.sh --role combo --non-interactive --gate-code=GOUT-01
```

**Prerequisites:** Ubuntu **24.04 LTS**, root access, internet during install,
4 GB RAM and 30 GB free disk. Ubuntu 22.04 fails — it has no python3.12.

**Quick vs advanced**

| Mode | Command | What happens |
|---|---|---|
| Quick (default) | `sudo ./install.sh` | No questions. Creates admin, site, areas, gates from `--topology`/`--tariff`, enables entry-gate daemons. Credentials go to `/etc/parking/install-notes.txt`. Wizard is skipped. |
| Advanced | `sudo ./install.sh --advanced` | Interactive installer, then a browser wizard (`/setup?token=…`) to choose everything yourself. Token is also at `/etc/parking/setup-token`. |

Every install ends with a **hard verification gate**: `sudo parking-doctor
--infra-only` must pass (services, DB, Redis, API, migrations at head,
events consumer alive, ARQ workers beating) or the installer exits
non-zero — no more "DONE with warnings". The installer adds the
`parking-doctor` shortcut to `/usr/local/bin`. Gate/camera checks still
happen after the setup wizard: `sudo parking-doctor`.

## Click-through install (flashdisk)

Copy the whole project to a USB stick, plug it into the target PC, double-click
`installer/E-Parking-Install.desktop` (or run `./installer/install-gui.sh`).
Agree -> pick role -> progress window -> the setup wizard opens in Chrome.
Needs internet until the offline bundle exists. Installs from the stick
(`PARKING_SOURCE_DIR`), no git/repo URL needed. Log: `/var/log/parking-install.log`.

Unattended / ISO first boot: `install-gui.sh --auto combo`, or install
`firstboot/eparking-firstboot.service` (reads `/etc/eparking-install.conf`).

## Roles

| Role     | What it installs                                                                |
|----------|---------------------------------------------------------------------------------|
| `server` | PostgreSQL 16, Redis 7, FastAPI (Gunicorn), ARQ workers, Nuxt frontend, nginx.  |
| `booth`  | Chrome kiosk, booth_bridge (serial→WS), udev rules. No DB, no API.              |
| `combo`  | Everything from `server` + booth-side kiosk pointed at `127.0.0.1`.             |

## After Install

**Quick mode (default):**

1. Open `http://<server-ip>/` and log in as `admin`.
2. Password: `sudo cat /etc/parking/install-notes.txt`.
3. **Device → Gates**: set each controller IP/port, press **Test buka/tutup**.
4. Entry-gate services: `sudo /opt/parking-system-v2/scripts/enable-gate-daemons.sh --run`.

**Advanced mode:**

1. Open the printed `/setup?token=…` link (token also in `/etc/parking/setup-token`).
2. The wizard creates site, admin, areas, gates. Each gate has a **Test buka/tutup** button.
3. Finish the wizard, then enable entry-gate services as above.

**Both modes:**

```bash
# Full health report (add --infra-only to skip gate/camera checks)
sudo parking-doctor
```

## Layout

```
installer/
├── setup.sh         ← dispatcher (called by ../install.sh)
├── README.md        ← this file
└── _roles/          ← role-specific installers (internal)
    ├── server/
    ├── booth_pc/
    └── combo/
```

Role-specific scripts under `_roles/` are still independently runnable for
debugging, but should not be invoked directly in normal field installs.

## Troubleshooting

| Symptom                          | Action                                                     |
|----------------------------------|------------------------------------------------------------|
| Daemon stuck PROCESSING/VALIDATING | `redis-cli del daemon:state:<CODE>` + restart unit       |
| Serial path drift after reboot   | `sudo scripts/write-udev-rules.sh` then update gate rows  |
| Gate test fails open             | `sudo parking-doctor --gate <CODE>` — first FAIL row tells you why |
