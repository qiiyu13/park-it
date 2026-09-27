#!/usr/bin/env python3
"""parking-doctor: one-shot field diagnostic for E-Parking v2.

Runs all checks a field technician needs to confirm software-to-hardware
wiring is healthy: DB, Redis, each gate's controller reachability, each
daemon's systemd unit + heartbeat freshness, booth POS linkage.

Exits 0 if all critical checks pass, 1 otherwise.

Usage:
    sudo -u parking python scripts/parking_doctor.py
    sudo -u parking python scripts/parking_doctor.py --json
    sudo -u parking python scripts/parking_doctor.py --gate GIN01
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger
from shared.redis import redis_client

logger = get_logger("parking_doctor")

ICON = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌", "SKIP": "·  "}


@dataclass
class Check:
    name: str
    category: str
    status: str = "PASS"
    message: str = ""
    fix: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def add(self, c: Check) -> Check:
        self.checks.append(c)
        return c

    def summary(self) -> dict[str, Any]:
        total = len(self.checks)
        by = {s: sum(1 for c in self.checks if c.status == s) for s in ("PASS", "WARN", "FAIL", "SKIP")}
        return {
            "total": total,
            **{s.lower(): n for s, n in by.items()},
            "duration_seconds": round(time.time() - self.started_at, 2),
            "healthy": by["FAIL"] == 0,
        }

    def render_text(self) -> str:
        lines = ["", "=" * 64, "  PARKING-DOCTOR — Field Diagnostic", f"  {datetime.now().isoformat(timespec='seconds')}", "=" * 64]
        cur = ""
        for c in self.checks:
            if c.category != cur:
                cur = c.category
                lines.append(f"\n[{cur}]")
            msg = c.message or "OK"
            lines.append(f"  {ICON[c.status]} {c.name:<40} {msg}")
            if c.fix and c.status in ("FAIL", "WARN"):
                lines.append(f"      → fix: {c.fix}")
        s = self.summary()
        lines += [
            "",
            "=" * 64,
            f"  TOTAL {s['total']}  |  ✅ {s['pass']}  ⚠️  {s['warn']}  ❌ {s['fail']}  ·  {s['skip']}  |  {s['duration_seconds']}s",
        ]
        lines.append("  🚀 ALL HEALTHY" if s["healthy"] else "  ⛔ FAILURES — fix above before going live")
        lines.append("=" * 64)
        return "\n".join(lines)


def time_it(fn):
    async def wrapper(*args, **kwargs):
        t0 = time.time()
        check = await fn(*args, **kwargs) if asyncio.iscoroutinefunction(fn) else fn(*args, **kwargs)
        if isinstance(check, Check):
            check.duration_ms = (time.time() - t0) * 1000
        return check
    return wrapper


def tcp_probe(host: str, port: int, timeout: float = 2.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} reachable"
    except OSError as e:
        return False, f"{host}:{port} — {e}"


def systemd_active(unit: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True, text=True, timeout=3,
        )
        out = r.stdout.strip()
        return r.returncode == 0 and out == "active", out or "unknown"
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, str(e)


async def check_database(report: Report) -> None:
    c = Check("PostgreSQL connect", "Core")
    t0 = time.time()
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        c.message = "connected"
    except Exception as e:
        c.status = "FAIL"
        c.message = str(e)[:120]
        c.fix = "Check DB_HOST/DB_PORT/credentials in .env; verify postgres systemd is up."
    c.duration_ms = (time.time() - t0) * 1000
    report.add(c)


async def check_redis_ping(report: Report) -> None:
    c = Check("Redis ping", "Core")
    t0 = time.time()
    try:
        await redis_client.connect()
        await redis_client.client.ping()
        c.message = "PONG"
    except Exception as e:
        c.status = "FAIL"
        c.message = str(e)[:120]
        c.fix = "Verify redis-server systemd active; check REDIS_HOST/PORT/PASSWORD."
    c.duration_ms = (time.time() - t0) * 1000
    report.add(c)


async def check_api_health(report: Report) -> None:
    c = Check("API /api/health", "Core")
    t0 = time.time()
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=2) as r:
            ok = r.status == 200
            c.message = "200 OK" if ok else f"HTTP {r.status}"
            if not ok:
                c.status = "FAIL"
    except Exception as e:
        c.status = "FAIL"
        c.message = str(e)[:120]
        c.fix = "systemctl status parking-api; journalctl -u parking-api -n 50"
    c.duration_ms = (time.time() - t0) * 1000
    report.add(c)


async def check_migrations(report: Report) -> None:
    """alembic current must equal heads.

    A missed migration means runtime 500s the moment new code touches a
    missing column — and nothing else in the stack reports it.
    """
    c = Check("Migrations at head", "Core")
    t0 = time.time()
    try:
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        cur = subprocess.run(
            [sys.executable, "-m", "alembic", "current"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, env=env,
        )
        heads = subprocess.run(
            [sys.executable, "-m", "alembic", "heads"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, env=env,
        )
        if cur.returncode != 0:
            c.status = "FAIL"
            c.message = f"alembic current failed: {(cur.stderr or '').strip()[:100]}"
            c.fix = "cd /opt/parking-system-v2 && .venv/bin/alembic current"
        else:
            head_revs = {
                line.split()[0]
                for line in heads.stdout.splitlines()
                if line.strip() and not line.startswith("#")
            }
            current_rev = None
            for line in cur.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith(("INFO", "Running")):
                    continue
                rev = line.split()[0]
                if rev != "<none>":
                    current_rev = rev  # last applied revision = bottom line
            if current_rev is None:
                c.status = "FAIL"
                c.message = "database has no revision (empty schema?)"
                c.fix = "cd /opt/parking-system-v2 && .venv/bin/alembic upgrade head"
            elif current_rev in head_revs:
                c.message = f"at {current_rev}"
            else:
                c.status = "FAIL"
                c.message = f"at {current_rev}, head is {'/'.join(sorted(head_revs))}"
                c.fix = "cd /opt/parking-system-v2 && .venv/bin/alembic upgrade head"
    except Exception as e:
        c.status = "FAIL"
        c.message = str(e)[:120]
        c.fix = "run alembic manually from /opt/parking-system-v2"
    c.duration_ms = (time.time() - t0) * 1000
    report.add(c)


async def check_events_consumer(report: Report) -> None:
    """Freshness of the event consumer's Redis heartbeat.

    The unit being 'active' proves nothing: the Pub/Sub loop can die inside
    a running process (one Redis blip used to do exactly that) while every
    gate event goes unprocessed — ticket buttons silent, no transactions.
    The consumer writes this key every 30s (TTL 90s) only while its
    subscribe loop has been healthy recently.
    """
    c = Check("Event consumer alive", "Core")
    t0 = time.time()
    try:
        await redis_client.connect()
        ttl = await redis_client.client.ttl("heartbeat:event-consumer")
        if ttl > 0:
            c.message = f"beating (ttl={ttl}s)"
        else:
            c.status = "FAIL"
            c.message = "no heartbeat — consumer dead or its subscribe loop is broken"
            c.fix = (
                "systemctl status parking-events && "
                "journalctl -u parking-events -n 50"
            )
    except Exception as e:
        c.status = "FAIL"
        c.message = f"redis read failed: {e}"[:120]
        c.fix = "Verify redis-server is up; check REDIS_HOST in .env"
    c.duration_ms = (time.time() - t0) * 1000
    report.add(c)


async def check_arq_workers(report: Report) -> None:
    """ARQ worker health-check keys (settings set health_check_interval=60).

    Unit 'active' covers process existence; the key proves the worker's run
    loop is actually executing (it is refreshed every ~60s with a 61s TTL).
    """
    for queue, unit in (
        ("critical", "parking-worker-critical"),
        ("background", "parking-worker-bg"),
    ):
        c = Check(f"ARQ worker {queue}", "Core")
        t0 = time.time()
        try:
            await redis_client.connect()
            ttl = await redis_client.client.ttl(f"arq:queue:{queue}:health-check")
            if ttl > 0:
                c.message = f"beating (ttl={ttl}s)"
            else:
                c.status = "FAIL"
                c.message = "no health key — worker not running or crashed"
                c.fix = f"systemctl status {unit} && journalctl -u {unit} -n 50"
        except Exception as e:
            c.status = "FAIL"
            c.message = f"redis read failed: {e}"[:120]
        c.duration_ms = (time.time() - t0) * 1000
        report.add(c)


async def load_gates(only: str | None) -> list[dict]:
    """Load gates from DB as dicts (avoid ORM dependency on full app context)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(get_settings().database_url)
    q = text("""
        SELECT id, code, name, direction, protocol,
               controller_host, controller_port, controller_device, controller_baudrate,
               gate_open_timeout_s, is_active, hardware_config
        FROM gates
        WHERE is_active = true
        ORDER BY direction, code
    """)
    async with engine.connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    await engine.dispose()
    gates = [dict(r) for r in rows]
    if only:
        gates = [g for g in gates if g["code"] == only]
    return gates


async def load_rows(query: str) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    eng = create_async_engine(get_settings().database_url)
    async with eng.connect() as conn:
        rows = (await conn.execute(text(query))).mappings().all()
    await eng.dispose()
    return [dict(r) for r in rows]


async def check_cameras(report: Report) -> None:
    """RTSP probe via ffprobe with short timeout."""
    try:
        cams = await load_rows(
            "SELECT id, name, rtsp_url FROM cameras WHERE is_active = true AND rtsp_url IS NOT NULL"
        )
    except Exception:
        return  # table may not exist on partial installs
    if not cams:
        c = Check("No active cameras", "Cameras")
        c.status = "SKIP"
        c.message = "no rows in cameras table"
        report.add(c)
        return
    ffprobe = "ffprobe"
    has_ffprobe = subprocess.run(["which", ffprobe], capture_output=True).returncode == 0
    for cam in cams:
        c = Check(f"cam {cam['name']}", "Cameras")
        if not has_ffprobe:
            c.status = "WARN"
            c.message = "ffprobe missing — install ffmpeg to probe RTSP"
            c.fix = "sudo apt install -y ffmpeg"
            report.add(c)
            continue
        url = cam["rtsp_url"]
        try:
            r = subprocess.run(
                [ffprobe, "-v", "error", "-rtsp_transport", "tcp",
                 "-timeout", "3000000", "-show_entries", "stream=codec_name",
                 "-of", "default=nw=1:nk=1", url],
                capture_output=True, text=True, timeout=6,
            )
            if r.returncode == 0 and r.stdout.strip():
                c.message = f"stream ok ({r.stdout.strip().splitlines()[0]})"
            else:
                c.status = "FAIL"
                c.message = (r.stderr.strip().splitlines() or ["no stream"])[-1][:100]
                c.fix = f"verify URL reachable: ffprobe {url}; check camera power + creds"
        except subprocess.TimeoutExpired:
            c.status = "FAIL"
            c.message = "ffprobe timed out (>6s)"
            c.fix = "camera likely unreachable; ping its IP"
        except Exception as e:
            c.status = "WARN"
            c.message = str(e)[:100]
        report.add(c)


async def check_printers(report: Report) -> None:
    try:
        printers = await load_rows(
            "SELECT id, name, mode, ip_address, port, serial_device "
            "FROM printers WHERE is_active = true"
        )
    except Exception:
        return
    if not printers:
        c = Check("No active printers", "Printers")
        c.status = "SKIP"
        c.message = "no rows in printers table"
        report.add(c)
        return
    for p in printers:
        c = Check(f"printer {p['name']}", "Printers")
        mode = (p["mode"] or "").lower()
        if mode == "tcp" and p["ip_address"] and p["port"]:
            ok, msg = tcp_probe(p["ip_address"], p["port"])
            c.message = msg
            if not ok:
                c.status = "FAIL"
                c.fix = f"ping {p['ip_address']}; check printer power + network"
        elif mode in ("serial", "usb") and p["serial_device"]:
            dev = p["serial_device"]
            if Path(dev).exists():
                c.message = f"{dev} present"
                if not os.access(dev, os.W_OK):
                    c.status = "WARN"
                    c.message = f"{dev} present but not writable"
                    c.fix = f"sudo chmod 666 {dev} or add parking user to dialout group"
            else:
                c.status = "FAIL"
                c.message = f"{dev} missing"
                c.fix = "replug USB; ls /dev/usb/ /dev/serial/by-id/"
        else:
            c.status = "WARN"
            c.message = f"mode={mode} but no host/device configured"
        report.add(c)


async def check_booths(report: Report) -> None:
    """Server-side liveness check on every active booth.

    booth_bridge POSTs ``/api/pos/heartbeat`` every 15s; we compare
    ``pos.last_seen_at`` to wall-clock now() to surface dead booths before
    the field operator calls in. Thresholds (60s WARN, 5m FAIL) align with
    the admin UI badge so the two surfaces stay consistent.
    """
    try:
        booths = await load_rows(
            "SELECT id, code, name, ip_address, is_active, last_seen_at, last_status "
            "FROM pos WHERE is_active = true ORDER BY code"
        )
    except Exception as e:
        c = Check("Booth list", "Booths")
        c.status = "WARN"
        c.message = f"DB query failed: {e}"[:120]
        c.fix = "Run `alembic upgrade head` — last_seen_at/last_status may not be in the schema yet."
        report.add(c)
        return
    if not booths:
        c = Check("No active booths", "Booths")
        c.status = "SKIP"
        c.message = "no rows in pos table — server-only install?"
        report.add(c)
        return

    now = datetime.now(UTC)
    for b in booths:
        c = Check(f"booth {b['code']}", "Booths")
        last = b["last_seen_at"]
        ip = b["ip_address"] or "no IP"
        if last is None:
            c.status = "FAIL"
            c.message = f"never checked in ({ip})"
            c.fix = (
                f"On the booth: sudo systemctl status parking-booth-bridge; "
                f"sudo journalctl -u parking-booth-bridge -n 50. "
                f"Verify /etc/parking/booth.json has code=\"{b['code']}\"."
            )
        else:
            # last is a timezone-aware datetime from PostgreSQL.
            age_s = (now - last).total_seconds()
            status_blob = b.get("last_status") or {}
            rfid = status_blob.get("rfid_connected")
            gate = status_blob.get("gate_connected")
            ver = status_blob.get("bridge_version", "?")
            c.message = (
                f"seen {age_s:.0f}s ago ({ip}) "
                f"rfid={rfid} gate={gate} ver={ver}"
            )
            if age_s >= 300:
                c.status = "FAIL"
                c.fix = (
                    f"Booth {b['code']} has not checked in for {age_s:.0f}s. "
                    f"On that booth PC: sudo systemctl restart parking-booth-bridge."
                )
            elif age_s >= 60:
                c.status = "WARN"
                c.fix = (
                    f"Heartbeat is late ({age_s:.0f}s). "
                    f"Check network path booth→server, and journalctl on the booth."
                )
        report.add(c)


async def check_acquirers(report: Report) -> None:
    """Settlement SFTP reachability for any configured acquirer."""
    try:
        rows = await load_rows(
            "SELECT key, value FROM settings WHERE key LIKE '%settlement%' OR key LIKE '%acquirer%'"
        )
    except Exception:
        return
    if not rows:
        c = Check("Acquirer config", "Acquirers")
        c.status = "SKIP"
        c.message = "no settlement/acquirer rows in settings"
        report.add(c)
        return
    seen_hosts: set[tuple[str, int]] = set()
    for r in rows:
        val = r["value"]
        cfg: dict = {}
        if isinstance(val, dict):
            cfg = val
        elif isinstance(val, str):
            try:
                cfg = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                continue
        host = cfg.get("sftp_host") or cfg.get("host")
        port = cfg.get("sftp_port") or cfg.get("port") or 22
        if not host:
            continue
        key = (host, int(port))
        if key in seen_hosts:
            continue
        seen_hosts.add(key)
        c = Check(f"{r['key']} → {host}:{port}", "Acquirers")
        ok, msg = tcp_probe(host, int(port), timeout=3.0)
        c.message = msg
        if not ok:
            c.status = "FAIL"
            c.fix = f"verify firewall allows outbound to {host}:{port}; check VPN if required"
        report.add(c)


async def check_gates(report: Report, only: str | None) -> None:
    try:
        gates = await load_gates(only)
    except Exception as e:
        c = Check("Gate list", "Gates")
        c.status = "FAIL"
        c.message = f"DB query failed: {e}"[:120]
        report.add(c)
        return

    if not gates:
        c = Check("Gate list", "Gates")
        c.status = "WARN"
        c.message = "No active gates in DB"
        c.fix = "Add gates via setup wizard or POST /api/gates"
        report.add(c)
        return

    for g in gates:
        code = g["code"]

        # Config sanity
        cfg = Check(f"{code} config", "Gates")
        if g["gate_open_timeout_s"] is None:
            cfg.status = "FAIL"
            cfg.message = "gate_open_timeout_s is NULL — daemon will crash"
            cfg.fix = f"UPDATE gates SET gate_open_timeout_s=10 WHERE code='{code}'"
        else:
            cfg.message = f"timeout={g['gate_open_timeout_s']}s relay={g.get('hardware_config', {}).get('relay_mode', 'SINGLE')}"
        report.add(cfg)

        # Reachability
        reach = Check(f"{code} controller", "Gates")
        protocol = (g["protocol"] or "").lower()
        host, port = g["controller_host"], g["controller_port"]
        dev = g["controller_device"]
        if protocol in ("compass", "tcp") and host and port:
            ok, msg = tcp_probe(host, port)
            reach.message = msg
            if not ok:
                reach.status = "FAIL"
                reach.fix = f"ping {host}; check switch/cable; verify controller power"
        elif dev:
            if Path(dev).exists():
                reach.message = f"{dev} present @ {g['controller_baudrate'] or '?'} baud"
            else:
                reach.status = "FAIL"
                reach.message = f"{dev} missing"
                reach.fix = "ls -l /dev/serial/by-id/; run scripts/detect-serial-devices.sh; replug USB"
        else:
            reach.status = "WARN"
            reach.message = "No controller_host/port nor controller_device set"
            reach.fix = "Re-run setup wizard hardware step"
        report.add(reach)

        # systemd unit
        unit_kind = "gate-in" if g["direction"] == "IN" else "gate-out"
        unit = f"parking-daemon-{unit_kind}@{code}.service"
        sys_c = Check(f"{code} daemon", "Gates")
        active, state = systemd_active(unit)
        sys_c.message = f"{unit} → {state}"
        if not active:
            sys_c.status = "FAIL"
            sys_c.fix = f"sudo systemctl enable --now {unit}; journalctl -u {unit} -n 50"
        report.add(sys_c)

        # Heartbeat freshness
        hb = Check(f"{code} heartbeat", "Gates")
        try:
            await redis_client.connect()
            key = f"gate:heartbeat:{code}"
            val = await redis_client.client.get(key)
            ttl = await redis_client.client.ttl(key)
            if val is None:
                hb.status = "FAIL"
                hb.message = "no heartbeat in Redis"
                hb.fix = f"Check daemon is running; redis-cli del daemon:state:{code}; restart unit"
            else:
                hb.message = f"alive (ttl={ttl}s)"
        except Exception as e:
            hb.status = "WARN"
            hb.message = f"redis read failed: {e}"[:80]
        report.add(hb)


def check_directories(report: Report) -> None:
    dirs = [
        ("/var/lib/parking/snapshots", "Snapshots dir"),
        ("/var/lib/parking/settlements", "Settlements dir"),
        ("/var/lib/parking/logs", "Logs dir"),
    ]
    for path, name in dirs:
        c = Check(name, "Filesystem")
        p = Path(path)
        if not p.exists():
            c.status = "FAIL"
            c.message = f"{path} missing"
            c.fix = f"sudo mkdir -p {path} && sudo chown parking:parking {path}"
        elif not os.access(p, os.W_OK):
            c.status = "FAIL"
            c.message = f"{path} not writable"
            c.fix = f"sudo chown parking:parking {path}"
        else:
            c.message = path
        report.add(c)


def check_core_units(report: Report) -> None:
    for unit in (
        "parking-api",
        "parking-worker-critical",
        "parking-worker-bg",
        "nginx",
        "postgresql",
        "redis-server",
    ):
        c = Check(unit, "Services")
        active, state = systemd_active(unit)
        c.message = state
        if not active:
            c.status = "FAIL"
            c.fix = f"sudo systemctl status {unit}; sudo systemctl restart {unit}"
        report.add(c)


def check_booth_units(report: Report) -> None:
    # Units are named booth-bridge-<code>.service by the installer; the old
    # hardcoded parking-booth-bridge/parking-kiosk names never existed, so
    # this check failed on every healthy booth (red alarms nobody trusts).
    units = sorted(p.name for p in Path("/etc/systemd/system").glob("booth-bridge-*.service"))
    if Path("/etc/systemd/system/parking-kiosk.service").exists():
        units.append("parking-kiosk")
    if not units:
        c = Check("booth bridge unit", "Booth services")
        c.status = "FAIL"
        c.message = "no booth-bridge-*.service installed"
        c.fix = "re-run installer: sudo ./setup.sh --configure-only"
        report.add(c)
        return
    for unit in units:
        c = Check(unit, "Booth services")
        active, state = systemd_active(unit)
        c.message = state
        if not active:
            c.status = "FAIL"
            c.fix = f"sudo systemctl status {unit}; sudo systemctl restart {unit}"
        report.add(c)


def check_booth_serials(report: Report) -> None:
    """Probe known parking-* udev symlinks present on this booth PC."""
    candidates = sorted(Path("/dev").glob("parking-*"))
    if not candidates:
        c = Check("Parking serial symlinks", "Booth USB")
        c.status = "WARN"
        c.message = "no /dev/parking-* symlinks found"
        c.fix = "run scripts/write-udev-rules.sh on this booth or check udev rules"
        report.add(c)
        return
    for dev in candidates:
        c = Check(dev.name, "Booth USB")
        try:
            target = os.readlink(dev) if dev.is_symlink() else str(dev)
            writable = os.access(dev, os.W_OK)
            c.message = f"→ {target}" + ("" if writable else " (not writable)")
            if not writable:
                c.status = "WARN"
                c.fix = "sudo chmod 660 " + str(dev) + " or add user to dialout"
        except OSError as e:
            c.status = "FAIL"
            c.message = str(e)
        report.add(c)


def check_booth_to_server(report: Report) -> None:
    """Ping the configured API server from the booth."""
    # Resolution order: API_BASE_URL env → /etc/parking/booth.json (what the
    # bridge actually uses) → localhost. The old settings-attr fallback hit
    # 127.0.0.1:80 on the booth itself and failed on every remote booth.
    import urllib.parse

    api_base = os.environ.get("API_BASE_URL")
    if not api_base:
        try:
            api_base = json.loads(Path("/etc/parking/booth.json").read_text()).get(
                "api_base_url"
            )
        except Exception:
            api_base = None
    api_base = api_base or "http://127.0.0.1"
    parsed = urllib.parse.urlparse(api_base if "://" in api_base else f"http://{api_base}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    c = Check(f"API reach {host}:{port}", "Booth network")
    ok, msg = tcp_probe(host, port, timeout=2.0)
    c.message = msg
    if not ok:
        c.status = "FAIL"
        c.fix = f"ping {host}; check switch + cable; verify API_BASE_URL in .env"
    report.add(c)

    # API health
    c2 = Check("API /api/health (remote)", "Booth network")
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=3) as r:
            c2.message = f"HTTP {r.status}"
            if r.status != 200:
                c2.status = "FAIL"
    except Exception as e:
        c2.status = "FAIL"
        c2.message = str(e)[:100]
        c2.fix = "confirm server-side parking-api is up via parking-doctor on server"
    report.add(c2)


async def run_booth() -> Report:
    """Booth-PC diagnostic — no DB or Redis assumed locally."""
    report = Report()
    check_booth_units(report)
    check_booth_serials(report)
    check_booth_to_server(report)
    return report


async def run(only: str | None, infra_only: bool = False) -> Report:
    """Full server report. ``infra_only`` stops after the checks that must
    pass BEFORE the setup wizard (services, DB, Redis, API, migrations,
    events consumer, ARQ) — gates/cameras/printers are configured there and
    would false-alarm on a fresh install."""
    report = Report()
    check_core_units(report)
    check_directories(report)
    await check_database(report)
    await check_redis_ping(report)
    await check_api_health(report)
    await check_migrations(report)
    await check_events_consumer(report)
    await check_arq_workers(report)
    if infra_only:
        return report
    await check_gates(report, only)
    if only is None:
        await check_cameras(report)
        await check_printers(report)
        await check_booths(report)
        await check_acquirers(report)
    return report


DANGEROUS_PATTERNS = (
    "rm -rf /",
    "rm -rf ~",
    "dd ",
    "mkfs",
    "> /dev/sd",
    "chmod 777 /",
    ":(){",
)


def is_dangerous(cmd: str) -> bool:
    low = cmd.lower()
    return any(p in low for p in DANGEROUS_PATTERNS)


def run_interactive_fixes(report: Report, assume_yes: bool, allow_dangerous: bool) -> int:
    """Walk through FAIL/WARN checks. For each that has a `fix` line, prompt
    and optionally execute. Returns count of fixes attempted.

    The fix command is run with shell=True so multi-step suggestions like
    "X && Y" work. Caller must be root for most fixes.
    """
    attempted = 0
    fails = [c for c in report.checks if c.status == "FAIL" and c.fix]
    warns = [c for c in report.checks if c.status == "WARN" and c.fix]
    targets = fails + warns
    if not targets:
        print("\n  Nothing to fix — all checks pass or have no suggested fix.")
        return 0

    print(f"\n  Interactive fix mode — {len(fails)} FAIL, {len(warns)} WARN with suggested fixes.")
    print("  For each: y=run, n=skip, q=quit, ?=show check detail.\n")

    for c in targets:
        print(f"  {ICON[c.status]} [{c.category}] {c.name}")
        print(f"     problem: {c.message}")
        print(f"     fix:     {c.fix}")
        if is_dangerous(c.fix) and not allow_dangerous:
            print("     ⛔ refused: contains dangerous pattern. Re-run with --allow-dangerous.")
            print()
            continue

        if assume_yes:
            choice = "y"
        else:
            try:
                choice = input("     run? [y/N/q] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n  aborted by user")
                return attempted
        if choice == "q":
            print("  quitting fix mode.")
            return attempted
        if choice != "y":
            print("     skipped\n")
            continue

        attempted += 1
        try:
            r = subprocess.run(c.fix, shell=True, capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                print("     ✅ ok (rc=0)")
                if r.stdout.strip():
                    print(f"     stdout: {r.stdout.strip()[:300]}")
            else:
                print(f"     ❌ rc={r.returncode}")
                if r.stderr.strip():
                    print(f"     stderr: {r.stderr.strip()[:300]}")
        except subprocess.TimeoutExpired:
            print("     ❌ fix command timed out (>60s)")
        except Exception as e:
            print(f"     ❌ exception: {e}")
        print()
    return attempted


def main() -> None:
    ap = argparse.ArgumentParser(description="E-Parking v2 field diagnostic")
    ap.add_argument("--json", action="store_true", help="emit JSON report")
    ap.add_argument("--gate", help="limit gate checks to one code (e.g. GIN01)")
    ap.add_argument("--booth", action="store_true",
                    help="run booth-PC checks only (skip DB/Redis/API local; probe network to server, local serials, booth_bridge unit)")
    ap.add_argument("--infra-only", action="store_true",
                    help="core infrastructure only (services, DB, Redis, API, migrations, events consumer, ARQ) — what the installer gates on")
    ap.add_argument("--fix", action="store_true",
                    help="after report, walk through FAIL/WARN and prompt to run each fix")
    ap.add_argument("--yes", action="store_true",
                    help="with --fix, auto-confirm every fix (use with care)")
    ap.add_argument("--allow-dangerous", action="store_true",
                    help="permit fixes containing destructive patterns (rm -rf, dd, mkfs, ...)")
    args = ap.parse_args()

    configure_logging()
    try:
        if args.booth:
            report = asyncio.run(run_booth())
        else:
            report = asyncio.run(run(args.gate, infra_only=args.infra_only))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        logger.error("doctor_crashed", error=str(e))
        print(f"parking-doctor crashed: {e}", file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "summary": report.summary(),
            "checks": [c.to_dict() for c in report.checks],
        }, indent=2))
    else:
        print(report.render_text())

    if args.fix and not args.json:
        run_interactive_fixes(report, assume_yes=args.yes, allow_dangerous=args.allow_dangerous)
        print("\n  Re-run parking-doctor to verify fixes took effect.")

    sys.exit(0 if report.summary()["healthy"] else 1)


if __name__ == "__main__":
    main()
