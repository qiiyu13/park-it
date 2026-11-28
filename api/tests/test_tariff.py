"""Tests for tariff calculation engine."""

from datetime import datetime

import pytest

from api.app.services.tariff import (
    DEFAULT_TARIFF_CONFIG,
    TariffConfig,
    VehicleTypeRate,
    calculate_tariff,
    calculate_tariff_parts,
)


class TestCalculateTariff:
    """Test tariff calculation scenarios."""

    def test_grace_period(self):
        """No charge within grace period."""
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 10, 10, 0)  # 10 minutes

        fee = calculate_tariff(entry, exit_, "MOBIL", DEFAULT_TARIFF_CONFIG)
        assert fee == 0

    def test_one_hour(self):
        """Charge for one hour."""
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 11, 0, 0)

        fee = calculate_tariff(entry, exit_, "MOBIL", DEFAULT_TARIFF_CONFIG)
        assert fee == 5000

    def test_partial_hour_rounds_up(self):
        """Partial hour rounds up."""
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 11, 30, 0)  # 1.5 hours

        fee = calculate_tariff(entry, exit_, "MOBIL", DEFAULT_TARIFF_CONFIG)
        assert fee == 10000  # 2 hours * 5000

    def test_daily_cap(self):
        """Daily cap limits charge."""
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 23, 0, 0)  # 13 hours

        fee = calculate_tariff(entry, exit_, "MOBIL", DEFAULT_TARIFF_CONFIG)
        assert fee == 50000  # Daily cap, not 65000

    def test_motor_rate(self):
        """Motor rate is lower."""
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 12, 0, 0)  # 2 hours

        fee = calculate_tariff(entry, exit_, "MOTOR", DEFAULT_TARIFF_CONFIG)
        assert fee == 4000  # 2 * 2000

    def test_bus_rate(self):
        """Bus rate is higher."""
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 12, 0, 0)  # 2 hours

        fee = calculate_tariff(entry, exit_, "BUS", DEFAULT_TARIFF_CONFIG)
        assert fee == 20000  # 2 * 10000

    def test_exit_before_entry_raises(self):
        """Exit before entry raises ValueError."""
        entry = datetime(2026, 4, 25, 12, 0, 0)
        exit_ = datetime(2026, 4, 25, 10, 0, 0)

        with pytest.raises(ValueError):
            calculate_tariff(entry, exit_, "MOBIL", DEFAULT_TARIFF_CONFIG)

    def test_unknown_vehicle_type(self):
        """Unknown vehicle type raises ValueError."""
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 11, 0, 0)

        with pytest.raises(ValueError):
            calculate_tariff(entry, exit_, "TRUCK", DEFAULT_TARIFF_CONFIG)

    def test_custom_config(self):
        """Custom configuration works."""
        config = TariffConfig(
            vehicle_types={
                "TRUCK": VehicleTypeRate(hourly_rate=15000, daily_cap=150000),
            },
            grace_period_minutes=30,
        )

        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 11, 0, 0)

        fee = calculate_tariff(entry, exit_, "TRUCK", config)
        assert fee == 15000

    def test_multi_day_cap_is_per_day(self):
        """Daily cap scales per 24h block, not per whole stay (revenue leak)."""
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 28, 10, 0, 0)  # exactly 72h = 3 days

        fee = calculate_tariff(entry, exit_, "MOBIL", DEFAULT_TARIFF_CONFIG)
        assert fee == 150000  # 3 * 50000, not a single 50000 cap

    def test_progressive_first_hour_base_tariff(self):
        """Progressive: first hour = base_tariff, subsequent = hourly_rate."""
        config = TariffConfig(
            vehicle_types={
                "MOBIL": VehicleTypeRate(
                    hourly_rate=2000, daily_cap=0, base_tariff=5000, tariff_mode="progressive"
                ),
            }
        )
        entry = datetime(2026, 4, 25, 10, 0, 0)

        assert calculate_tariff(entry, datetime(2026, 4, 25, 11, 0, 0), "MOBIL", config) == 5000
        # 3 hours: 5000 + 2 * 2000
        assert calculate_tariff(entry, datetime(2026, 4, 25, 13, 0, 0), "MOBIL", config) == 9000

    def test_flat_mode_one_fee_per_visit(self):
        """Flat: same fee whether the stay is 2 or 5 hours."""
        config = TariffConfig(
            vehicle_types={
                "MOBIL": VehicleTypeRate(
                    hourly_rate=0, daily_cap=0, base_tariff=3000, tariff_mode="flat"
                ),
            }
        )
        entry = datetime(2026, 4, 25, 10, 0, 0)

        assert calculate_tariff(entry, datetime(2026, 4, 25, 12, 0, 0), "MOBIL", config) == 3000
        assert calculate_tariff(entry, datetime(2026, 4, 25, 15, 0, 0), "MOBIL", config) == 3000

    def test_per_type_grace_overrides_default(self):
        """grace_period_minutes=0 charges from the first minute."""
        config = TariffConfig(
            vehicle_types={
                "MOBIL": VehicleTypeRate(
                    hourly_rate=3000, daily_cap=0, grace_period_minutes=0
                ),
            }
        )
        entry = datetime(2026, 4, 25, 10, 0, 0)

        assert calculate_tariff(entry, datetime(2026, 4, 25, 10, 2, 0), "MOBIL", config) == 3000

    def test_overnight_midnight_surcharge(self):
        """Overnight surcharge added once per calendar-midnight crossed."""
        config = TariffConfig(
            vehicle_types={
                "MOBIL": VehicleTypeRate(
                    hourly_rate=5000,
                    daily_cap=0,
                    overnight_mode="midnight",
                    overnight_tariff=10000,
                ),
            }
        )
        entry = datetime(2026, 4, 25, 23, 0, 0)
        exit_ = datetime(2026, 4, 26, 1, 0, 0)  # 2h, crosses one midnight

        fee = calculate_tariff(entry, exit_, "MOBIL", config)
        assert fee == 20000  # 2 * 5000 + 1 * 10000

    def test_lost_ticket_penalty_added(self):
        """Default: denda is added to the time fee, grace ignored."""
        config = TariffConfig(
            vehicle_types={
                "MOBIL": VehicleTypeRate(
                    hourly_rate=5000, daily_cap=0, lost_ticket_penalty=50000
                ),
            }
        )
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 12, 5, 0)  # 3 started hours

        assert calculate_tariff_parts(
            entry, exit_, "MOBIL", config, is_lost_ticket=True
        ) == (15000, 50000)
        assert calculate_tariff(entry, exit_, "MOBIL", config, is_lost_ticket=True) == 65000
        assert calculate_tariff(entry, exit_, "MOBIL", config) == 15000

    def test_lost_ticket_penalty_floor(self):
        """Minimum-fee mode: charge at least the denda; only the top-up is denda."""
        config = TariffConfig(
            vehicle_types={
                "MOBIL": VehicleTypeRate(
                    hourly_rate=5000, daily_cap=0, lost_ticket_penalty=50000
                ),
            },
            lost_ticket_penalty_added=False,
        )
        entry = datetime(2026, 4, 25, 10, 0, 0)
        exit_ = datetime(2026, 4, 25, 10, 5, 0)  # within grace, but ticket lost

        assert calculate_tariff_parts(
            entry, exit_, "MOBIL", config, is_lost_ticket=True
        ) == (5000, 45000)
        assert calculate_tariff(entry, exit_, "MOBIL", config, is_lost_ticket=True) == 50000
