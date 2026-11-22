"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    configure_logging()
    logger.info("api_starting", app_name=app.title)

    settings = get_settings()
    logger.info(
        "api_config_loaded",
        env=settings.app_env,
        debug=settings.debug,
    )

    # Start WebSocket broadcaster. Safe per-worker: each worker fans out only to
    # its own connected sockets. The DB-mutating EventConsumer runs in its own
    # single-instance service (parking-events) — see event_consumer_main.py.
    from api.app.websocket.broadcaster import broadcaster
    await broadcaster.start()

    # Seed settings that newer features expect. Idempotent; never overwrites an
    # operator's choice.
    try:
        from sqlalchemy import select

        from api.app.models.setting import Setting
        from api.database import AsyncSessionLocal

        defaults = [
            (
                "lane_reset_mode",
                "time",
                "string",
                "Reset lane pakai apa (time / in3off / both)",
                "time = timer saja; in3off = tunggu sinyal IN3OFF saja; both = reset setelah IN3OFF dan timer keduanya terpenuhi. Bisa dioverride per gate.",
                "gate",
            ),
            (
                "lane_reset_seconds",
                "5",
                "int",
                "Jeda reset lane setelah kendaraan lewat (detik)",
                "Nilai global. Bisa dioverride per gate di form Gate (Jeda reset lane). Setelah IN3 / palang terbuka, lane siap lagi setelah N detik walau controller tidak mengirim IN3OFF.",
                "gate",
            ),
            (
                "member_anti_passback",
                "true",
                "bool",
                "Kartu member harus keluar dulu sebelum bisa masuk lagi",
                "ON: satu kartu hanya boleh punya satu kendaraan di dalam. OFF: kartu boleh masuk lagi, dibatasi setting maksimal kendaraan per kartu.",
                "member",
            ),
            (
                "member_max_vehicles",
                "1",
                "int",
                "Maksimal kendaraan per kartu (0 = tanpa batas)",
                "Dipakai saat anti-passback dimatikan. Isi 1 untuk perilaku sama, 2+ untuk beberapa kendaraan per kartu, 0 untuk tanpa batas.",
                "member",
            ),
            (
                "snapshot_keep_months",
                "6",
                "int",
                "Hapus Otomatis: simpan snapshot (bulan)",
                "Snapshot disimpan semua selama N bulan terakhir, yang lebih lama dihapus otomatis. Isi 0 untuk menyimpan selamanya.",
                "snapshot",
            ),
            (
                "pos_plate_prefix",
                "",
                "string",
                "Awalan plat nomor di POS keluar",
                "Kode kota yang otomatis muncul di isian plat POS (mis. H). Kosongkan bila plat diketik penuh.",
                "pos",
            ),
            (
                "pos_auto_print_receipt",
                "true",
                "bool",
                "Cetak nota otomatis di POS keluar",
                "Matikan bila nota hanya dicetak saat operator menekan F12.",
                "pos",
            ),
            (
                "emoney_enabled",
                "false",
                "bool",
                "Aktifkan pembayaran e-money",
                "Matikan bila lane tidak punya reader e-money — tombol E-Money di POS akan disembunyikan.",
                "payment",
            ),
            (
                "cash_auto_open",
                "true",
                "bool",
                "Palang otomatis terbuka setelah bayar tunai",
                "Aktif: tunai dikonfirmasi langsung membuka palang. Matikan untuk kembali ke layar 'Buka Palang' + tekan Space.",
                "payment",
            ),
        ]
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        async with AsyncSessionLocal() as db:
            for key, value, vtype, label, desc, group in defaults:
                # ON CONFLICT DO NOTHING: every uvicorn worker runs this hook,
                # so a plain INSERT raced and logged UniqueViolation noise.
                await db.execute(
                    pg_insert(Setting.__table__)
                    .values(
                        key=key,
                        value=value,
                        value_type=vtype,
                        label=label,
                        description=desc,
                        group=group,
                        is_system=False,
                    )
                    .on_conflict_do_nothing(index_elements=["key"])
                )
            await db.commit()
    except Exception as exc:  # seeding must never block startup
        logger.warning("default_settings_seed_failed", error=str(exc))

    yield

    # Shutdown
    await broadcaster.stop()
    logger.info("api_shutting_down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.2.0",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
    )

    # Metrics middleware (before CORS so all requests are tracked)
    from api.app.middleware.metrics import get_metrics_response, metrics_middleware

    app.middleware("http")(metrics_middleware)

    # Metrics endpoint
    @app.get("/metrics")
    async def metrics() -> Response:
        from api.app.middleware.metrics import (
            refresh_gate_online,
            refresh_queue_depths,
            refresh_settlement_files_metric,
        )

        await refresh_queue_depths()
        await refresh_gate_online()
        await refresh_settlement_files_metric()
        return get_metrics_response()

    # Rate limiting
    from api.app.middleware.rate_limit import RateLimitMiddleware

    app.add_middleware(RateLimitMiddleware)

    # Security headers (defense in depth — also set at nginx layer)
    from api.app.middleware.security_headers import create_security_headers_middleware

    app.middleware("http")(create_security_headers_middleware(enable_hsts=settings.app_env == "production"))

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    from api.app.routes import (
        abandoned_vehicles,
        areas,
        audit_logs,
        auth,
        cameras,
        emoney_readers,
        gates_unified,
        health,
        manual_open_logs,
        members,
        payments,
        pos,
        printers,
        reports,
        settlements,
        setup,
        shift_assignments,
        shifts,
        site_config,
        snapshots,
        transactions,
        users,
        vehicle_types,
        worker_sessions,
    )
    from api.app.routes import (
        settings as settings_routes,
    )
    from api.app.websocket import handlers as ws_handlers

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(gates_unified.router, prefix="/api")
    app.include_router(pos.router, prefix="/api")
    app.include_router(cameras.router, prefix="/api")
    app.include_router(settings_routes.router, prefix="/api")
    app.include_router(payments.router, prefix="/api")
    app.include_router(vehicle_types.router, prefix="/api")
    app.include_router(shifts.router, prefix="/api")
    app.include_router(shift_assignments.router, prefix="/api")
    app.include_router(worker_sessions.router, prefix="/api")
    app.include_router(areas.router, prefix="/api")
    app.include_router(emoney_readers.router, prefix="/api")
    app.include_router(members.router, prefix="/api")
    app.include_router(transactions.router, prefix="/api")
    app.include_router(manual_open_logs.router, prefix="/api")
    app.include_router(abandoned_vehicles.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(site_config.router, prefix="/api")
    app.include_router(settlements.router, prefix="/api")
    app.include_router(audit_logs.router, prefix="/api")
    app.include_router(printers.router, prefix="/api")
    app.include_router(snapshots.router, prefix="/api")
    app.include_router(setup.router, prefix="/api")

    # WebSocket
    app.include_router(ws_handlers.router)

    return app


# Global app instance for uvicorn
app = create_app()
