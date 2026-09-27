# E-Parking v2 Installer

One entry point. Pick a role.

```bash
sudo ./setup.sh                # interactive role prompt
sudo ./setup.sh --role server  # full backend stack
sudo ./setup.sh --role booth   # booth PC (kiosk + booth_bridge)
sudo ./setup.sh --role combo   # server + on-box booth (single-PC site)

# Unattended (CI / scripted field rolls). Non-interactive requires a role;
# booth configure additionally needs server IP + enrollment token:
sudo ./setup.sh --role server --non-interactive
sudo ./setup.sh --role booth --non-interactive \
    --server-ip=192.168.1.100 --token=<enroll-token> \
    --booth-code=BOOTH_02 --gate-code=GOUT-02
sudo ./setup.sh --role combo --non-interactive --gate-code=GOUT-01
```

Every install ends with a **hard verification gate**: `parking-doctor
--infra-only` must pass (services, DB, Redis, API, migrations at head,
events consumer alive, ARQ workers beating) or the installer exits
non-zero — no more "DONE with warnings". Gate/camera checks still happen
after the setup wizard: `sudo -u parking python scripts/parking_doctor.py`.

## Roles

| Role     | What it installs                                                                |
|----------|---------------------------------------------------------------------------------|
| `server` | PostgreSQL 16, Redis 7, FastAPI (Gunicorn), ARQ workers, Nuxt frontend, nginx.  |
| `booth`  | Chrome kiosk, booth_bridge (serial→WS), udev rules. No DB, no API.              |
| `combo`  | Everything from `server` + booth-side kiosk pointed at `127.0.0.1`.             |

## After Install

1. Verify services: `sudo systemctl status parking-api parking-worker-critical`
2. Open `http://<server-ip>` and run the setup wizard.
3. Add gates in wizard. Each row gets a **Test buka/tutup** button — confirms wiring end-to-end before you finalize.
4. Run field diagnostic any time:
   ```bash
   sudo -u parking python scripts/parking_doctor.py
   ```

## Layout

```
installer/
├── setup.sh         ← dispatcher (the one tech runs)
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
| Gate test fails open             | `parking-doctor --gate <CODE>` — first FAIL row tells you why |
