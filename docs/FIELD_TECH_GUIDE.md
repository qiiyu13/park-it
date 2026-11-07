# Field Technician Guide — E-Parking v2

> Zero-to-running walkthrough for a field technician installing E-Parking v2 at a
> customer site. Follow top to bottom on a fresh Ubuntu 22.04 box. Expected time
> for a single-gate site: **2–4 hours** if hardware behaves.

---

## 0. What You Need Before You Arrive

### Hardware

| Item                       | Notes                                                            |
|----------------------------|------------------------------------------------------------------|
| Server PC (Ubuntu 22.04)   | 4 cores, 8 GB RAM, 50 GB SSD, static IP capable                   |
| Network switch (managed)   | All gates + booth + server on same VLAN                          |
| Gate controllers           | Compass (TCP, RJ45) **or** Interface barrier (USB serial)         |
| Booth PC                   | Per booth. Can be the server itself for single-PC sites.          |
| Thermal printer            | ESC/POS, USB                                                      |
| Cameras                    | RTSP-capable, RJ45                                                |
| E-money reader (PASSTI) or | USB serial                                                       |
| Booth Bridge (Mandiri)     | RS-232 + bridge box                                              |
| Barcode scanner            | USB HID                                                          |
| Patch cables, power, UPS   | Bring spares                                                     |

### Software / credentials

- Repository URL (git, with read access)
- DB password (or generate on-site)
- Customer site name + tariff plan
- Mandiri / BRI / BNI / BCA acquirer credentials (if e-money)

---

## 1. Physical Wiring (do this first, power on, leave running)

1. Mount server in equipment cabinet. Power it on. Connect to switch.
2. Cable each **TCP gate controller** to switch. Assign static IP per the site
   plan — recommended `192.168.1.100+` for gates, `.200+` for booths.
3. Plug each **serial gate** USB cable into the assigned booth PC. Don't worry
   about which `/dev/ttyUSB*` it lands on — the wizard pins a stable symlink later.
4. Plug printer, e-money reader, scanner, cameras into their booth PC.
5. Manually trigger every gate **once** with the controller's local button to
   confirm the barrier mechanically opens and closes. If a gate jams here, the
   software cannot fix it — call the gate vendor before continuing.

---

## Workshop vs. on-site (two-phase install)

Software can be installed in the workshop and the hardware wired on-site later:

- **Workshop:** image the PC, run the installer. Needs no hardware connected.
  - Server: `sudo ./install.sh --advanced` (guided wizard) or `sudo ./install.sh` (defaults).
  - Combo: `sudo ./install.sh --combo`.
  - Booth: `sudo ./install.sh --booth --server-ip <ip> --token <token>`.
- **On-site:** after the box has its real network address:
  - Server: `sudo scripts/field-reconfig.sh` — fixes `CORS_ORIGINS` for the
    site IP, restarts the API, and mints a fresh wizard token (the workshop
    token expires after 24h). Prints the `/setup?token=…` URL.
  - Booth: `sudo installer/_roles/booth_pc/setup.sh --configure-only` — asks
    device paths, gate code, and the server's `INTERNAL_API_KEY`, then writes
    `booth.json` and starts the bridge.

A single-visit install (no workshop pre-stage) just runs the installer with no
phase flag — both phases run back to back, same as before.

If you only need a new wizard token (token expired, lost the URL):
`sudo scripts/regen-setup-token.sh`.

---

## 2. Install the Software

```bash
# On the server
git clone <repo-url> /tmp/parking-system-v2
cd /tmp/parking-system-v2
sudo ./install.sh
```

`install.sh` is the only entry point (`installer/setup.sh` is internal). Roles:

- **server** — backend only (most common for multi-PC sites)
- **booth** — booth PC only (`--booth --server-ip <ip> --token <token>`)
- **combo** — server + booth on one machine (single-PC sites)

`sudo ./install.sh` runs with defaults and asks **nothing**. `--advanced`
prompts for server IP, PostgreSQL password, JWT secret (blank = generate) and
repository URL, then opens the wizard.

Both modes handle PostgreSQL 16, Redis 7, the Python venv, the Nuxt build,
nginx, systemd units, and all DB migrations.

### Verify the stack came up

```bash
sudo systemctl status parking-api parking-worker-critical parking-worker-bg nginx postgresql redis-server
curl http://localhost/api/health    # expect {"status":"ok"}
```

If any service is `failed`, jump to §7 Troubleshooting before proceeding.

---

## 3. Run the Setup Wizard (`--advanced` only)

Quick installs skip this section — admin, site, areas and gates already exist;
log in with the password from `/etc/parking/install-notes.txt`.

Open the printed `http://<server-ip>/setup?token=…` link in a browser (token is
also in `/etc/parking/setup-token`). The wizard takes you through:

1. **First admin** — pick username/password. Weak demo credentials (`admin` /
   `admin123`) are never created by a production install.
2. **Site config** — name, currency (IDR), tariff plan.
3. **Areas + vehicle types** — at minimum: "Umum" area, "Mobil" + "Motor" types.
4. **Hardware detect** — click the detect button. The wizard runs
   `scripts/detect-serial-devices.sh` and lists every USB serial it sees. For
   each one, click **Pasang /dev/parking-...** to write a stable udev symlink
   keyed by USB vendor/product/serial. After this step, `/dev/ttyUSB0` will
   never renumber on you again.
5. **Gates** — add one row per controller:
   - `code` short and unique, dashed form (`GIN-01`, `GOUT-01`)
   - `direction` IN or OUT
   - For TCP: `controller_host` + `controller_port` (default 5000)
   - For serial: `controller_device` = `/dev/parking-gate-<code>` (the symlink
     from step 4) + baudrate (usually 9600)
   - `relay_mode`: SINGLE (controller auto-closes via loop sensor) or DUAL
     (you send explicit close commands)
   - `gate_open_timeout_s`: defaults to 10. Don't leave blank.
   - **hardware_config.display.enabled**: leave **false** unless the
     controller has a physical display module. Sending `cmd_ds` to a
     module-less controller will disconnect it.
   - **hardware_config.audio.enabled**: true only if an MP3 module is wired.
6. **Booths** — one row per booth PC. Set `IP Address` + the default gate it
   serves. Then go back into each gate and link it to its booth via the POS
   field.
7. **Peripherals** — assign printer + e-money reader to each booth.
8. **Finalize** — flips `setup_complete=true` and runs
   `scripts/enable-gate-daemons.sh`, which spawns one systemd unit per gate.

### Per-gate end-to-end test (in the wizard, before clicking Finalize)

Each gate row has a **Test buka/tutup** button. Click it. The wizard publishes a
real `OpenGate` command on Redis, waits for the daemon to ACK with a
`gate_opened` event, and shows the round-trip latency. For DUAL relay gates it
also fires a Close + waits for `gate_closed`.

A green pill + a number around 200–800 ms means the full pipeline works (DB →
Redis Stream → daemon → controller → physical relay → daemon event → API). A
red pill means stop and debug **this** gate before touching the others — first
look at `sudo parking-doctor --gate <CODE>` output (see §6).

---

## 4. Booth PC (if separate from the server)

On each booth PC:

```bash
cd parking-system-v2            # installer copy / repo on the booth PC
sudo ./install.sh --booth --server-ip <server-ip> --token <enrollment-token>
# Two-phase (workshop then field):
#   sudo ./install.sh --booth --install-only
#   sudo ./install.sh --booth --configure-only --server-ip <ip> --token <token>
```

Installs Chrome in kiosk mode pointed at `http://<server-ip>` and the
`booth_bridge` service that forwards Mandiri eMoney serial events to the
API as a WebSocket client.

---

## 5. Smoke Test (do every path)

Run each path at least twice. If any one of these fails, **do not hand over** to
the customer.

### Entry (gate-in)

1. Pull a car up to the entry loop.
2. Loop sensor fires → `vehicle_detected` event → ticket prints (thermal
   printer should fire within ~1 s) → barrier opens.
3. Car drives through → close-sensor (or relay-mode timer) closes barrier.

### Exit — cash (two-step on purpose)

1. Scan ticket at booth → tariff shown on POS.
2. Operator clicks **Pay** → receipt prints.
3. Operator confirms by pressing **Space** (or a hardware button) → barrier
   opens.
4. Cash flow is two-step deliberately, so the operator can take the money
   before the barrier moves. Don't "fix" this by auto-opening.

### Exit — e-money (auto-opens)

1. Driver taps card on PASSTI reader (manless) **or** the booth bridge (attended).
2. API verifies via the acquirer in <2 s → barrier auto-opens.
3. Settlement file is queued by the background worker for end-of-day SFTP.

### Exit — RFID member

1. Driver taps RFID card → barrier auto-opens (no payment, member is on a plan).

---

## 6. Field Diagnostic — `parking-doctor`

The single most useful command when something looks off:

```bash
sudo parking-doctor
```

It checks: core systemd units, on-disk directories, PostgreSQL, Redis, API
health, then for each active gate: config sanity (no NULL timeouts, relay mode
set), controller reachability (TCP probe or serial path stat), daemon unit
state, heartbeat freshness in Redis. Each FAIL row prints a `→ fix:` line with
the exact next command.

Common forms:

```bash
sudo parking-doctor                       # full health table on the server
sudo parking-doctor --gate GIN-01          # focus one gate
sudo parking-doctor --json                # for piping into the wizard or a monitor
sudo parking-doctor --booth               # run on a booth PC (no DB/Redis required)
sudo parking-doctor --fix                 # interactively run each suggested fix
sudo parking-doctor --fix --yes           # auto-confirm every fix (use with care)
sudo parking-doctor --fix --allow-dangerous   # permit rm -rf / dd / mkfs in fixes
```

Exit code is 0 if every check passes, 1 otherwise.

The doctor now also probes cameras (RTSP via ffprobe), printers (TCP or
serial), and configured acquirer SFTP hosts. On booth PCs, `--booth` skips
the DB-bound checks and instead verifies the `parking-booth-bridge` /
`parking-kiosk` units, the `/dev/parking-*` USB symlinks, and reachability
to the server.

---

## 7. Troubleshooting

### Daemon stuck in PROCESSING / VALIDATING after restart

```bash
sudo systemctl stop parking-daemon-gate-in@GIN-01
redis-cli -a <REDIS_PASSWORD> del "daemon:state:GIN-01"
sudo systemctl start parking-daemon-gate-in@GIN-01
```

The daemon persists its state to Redis so it can resume after a crash. If it
crashed mid-transaction the persisted state can be inconsistent — clearing it
is the safe reset.

### TCP controller drops connection immediately

```bash
# In the gate row, ensure hardware_config = {"display": {"enabled": false}, ...}
# Then restart the daemon.
```

Compass controllers without a display module reject `cmd_ds` and close the
socket. The migration `a3f4b1d2e5c6_gate_sane_defaults` sets the default to
`false`, but older rows may still be `true`.

### Cash payment doesn't open the gate after operator confirms

Exit lanes have **no daemon** — `booth_bridge` drives the exit relay directly
(the `gate_out` daemon was removed). Cash exit is two-step: after the receipt
prints, the operator presses Space/button and `booth_bridge` fires the local
relay open, then closes after `close_delay_seconds`. If the gate never moves:

```bash
# On the booth PC (where the relay USB is plugged in):
journalctl -u booth-bridge -n 200
# Confirm the relay device symlink exists:
ls -l /dev/parking-*
```

Common causes: relay USB not mapped to a `/dev/parking-*` symlink, wrong
serial open/close hex in the gate's `hardware_config`, or `booth-bridge`
not running on that booth PC.

### Serial port renumbered after reboot

Don't manually fix `/dev/ttyUSB0` vs `ttyUSB1`. Instead:

```bash
sudo /opt/parking-system-v2/scripts/write-udev-rules.sh
```

This rewrites `/etc/udev/rules.d/99-parking-gates.rules` based on the gate
rows currently in the DB, pins each by USB vendor/product/serial, and prints
the SQL to update each `controller_device` field to the stable `/dev/parking-gate-*`
path.

### API returns 502 from nginx

```bash
sudo systemctl status parking-api
sudo journalctl -u parking-api -n 100
sudo nginx -t && sudo systemctl restart nginx
```

Usually means `parking-api` is down. Common root causes: DB password wrong in
`.env`, port 8000 already taken, or migrations haven't been applied.

### Postgres / Redis ordering

Docker (PostgreSQL + Redis + pgbouncer) **must** be up before uvicorn / the API
service starts. The `parking-api` unit has `After=` directives for these, but
if you start things manually for debugging, mind the order. `parking-doctor`
will catch this and tell you which service is down.

---

## 8. Harden Before Leaving Site

- [ ] Change every default password (admin, postgres, JWT_SECRET, INTERNAL_API_KEY).
- [ ] Restrict `CORS_ORIGINS` in `.env` to the actual host (no `*`).
- [ ] Rotate `INTERNAL_API_KEY` and copy the new value into every booth PC.
- [ ] Enable nightly DB backup: `sudo crontab -e` →
      `0 2 * * * /opt/parking-system-v2/scripts/backup_database.sh`.
- [ ] Run `scripts/security_scan.py` and resolve every WARN.
- [ ] Run `parking-doctor` one last time — exit 0 before you hand over.
- [ ] Walk through §5 smoke tests **with the customer's operator** so they see
      a clean run.

---

## 9. Handover Cheat Sheet (leave a printed copy at the site)

```
HEALTH CHECK   sudo -u parking .venv/bin/python /opt/parking-system-v2/scripts/parking_doctor.py
RESTART API    sudo systemctl restart parking-api
RESTART GATE   sudo systemctl restart parking-daemon-gate-in@GIN-01
LOGS           sudo journalctl -u parking-api -f
WIPE STATE     redis-cli -a <pw> del "daemon:state:<CODE>"
BACKUP NOW     sudo -u postgres pg_dump parking | gzip > /backup/parking_$(date +%F).sql.gz
WIZARD AGAIN   browse to http://<server-ip>/setup?force=1 (admin JWT required)
```

---

## 10. When to Escalate

Call engineering if **any** of these is true after 30 minutes of debugging:

- `parking-doctor` still reports FAIL after applying every `→ fix:` it prints.
- A gate test (§3) succeeds via the wizard button but the smoke test (§5) fails
  the same gate — pipeline-vs-physical mismatch.
- E-money payment is approved by the acquirer but the gate never opens.
- Settlement file doesn't appear in `/var/lib/parking/settlements/` after a
  paid transaction.
- Any daemon's heartbeat goes stale (>60 s) repeatedly without an obvious
  crash in `journalctl`.

Include the output of `parking-doctor --json` and the last 200 lines of
`journalctl -u parking-api` in the escalation ticket.

---

*Last updated: 2026-05-20*
