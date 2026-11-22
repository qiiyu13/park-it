"""Tariff calculation engine.

This module provides configurable tariff calculation. Rates are not hardcoded;
they are passed as parameters, allowing the system to be configured at setup time
or changed dynamically via the admin settings.

Pricing model (per vehicle type):

* ``grace_period_minutes`` — stays at or under this are free.
* ``base_tariff`` — flat charge for the first hour ("jam pertama").
* ``hourly_rate`` — charge for each *subsequent* started hour.
* ``tariff_mode`` — ``"flat"``: one fixed fee per visit (``base_tariff``, or
  ``hourly_rate`` if that is 0). ``"hourly"``: ``hourly_rate`` per started hour
  (``base_tariff`` is the fallback when ``hourly_rate`` is 0). ``"progressive"``:
  first hour ``base_tariff``, every hour after that ``hourly_rate``.
* ``grace_period_minutes`` on a rate overrides the config default (0 = no free
  period).
* ``overnight_mode`` / ``overnight_tariff`` — ``"midnight"`` adds the surcharge
  once per calendar-date boundary crossed; ``"24h"`` adds it once per full 24h
  block; ``"none"`` disables it.
* ``daily_cap`` — caps the time-based fee per 24h block (0 = no cap).
* ``lost_ticket_penalty`` — when the ticket is lost the fee is at least this
  amount (a floor, applied on top of / instead of the measured-time fee).

Example configuration (stored in Setting model or config file):
    {
        "vehicle_types": {
            "MOTOR": {"hourly_rate": 2000, "daily_cap": 15000},
            "MOBIL": {"hourly_rate": 5000, "daily_cap": 50000}
        },
        "grace_period_minutes": 15
    }
"""

from dataclasses import dataclass
from datetime import datetime
from math import ceil

MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 60 * 24


@dataclass
class VehicleTypeRate:
    """Rate configuration for a vehicle type."""

    hourly_rate: int  # Rupiah per started hour (subsequent hours if progressive)
    daily_cap: int  # Maximum time-based charge per 24h block (0 = no cap)
    base_tariff: int = 0  # Flat charge for the first hour
    overnight_mode: str = "none"  # "midnight" | "24h" | "none"
    overnight_tariff: int = 0  # Surcharge per night
    lost_ticket_penalty: int = 0  # Minimum fee floor when ticket is lost
    tariff_mode: str = "hourly"  # "flat" | "hourly" | "progressive"
    grace_period_minutes: int | None = None  # None = use TariffConfig default


@dataclass
class TariffConfig:
    """Complete tariff configuration."""

    vehicle_types: dict[str, VehicleTypeRate]
    grace_period_minutes: int = 15


def calculate_tariff(
    entry_time: datetime,
    exit_time: datetime,
    vehicle_type_code: str,
    config: TariffConfig,
    *,
    is_lost_ticket: bool = False,
) -> int:
    """Calculate parking fee based on entry/exit time and vehicle type.

    Args:
        entry_time: When vehicle entered
        exit_time: When vehicle exited
        vehicle_type_code: Key in config.vehicle_types (e.g. "MOTOR", "MOBIL")
        config: Tariff configuration
        is_lost_ticket: Apply the lost-ticket penalty floor and bypass grace

    Returns:
        Fee in Rupiah

    Raises:
        ValueError: If exit precedes entry or the vehicle type is unknown
    """
    if exit_time < entry_time:
        raise ValueError("exit_time must be after entry_time")

    rate = config.vehicle_types.get(vehicle_type_code)
    if rate is None:
        raise ValueError(f"Unknown vehicle type: {vehicle_type_code}")

    duration_minutes = (exit_time - entry_time).total_seconds() / 60

    # Grace period: no charge (does not apply to lost tickets).
    grace = (
        rate.grace_period_minutes
        if rate.grace_period_minutes is not None
        else config.grace_period_minutes
    )
    if not is_lost_ticket and duration_minutes <= grace:
        return 0

    # Round up to whole started hours (minimum 1 once past grace).
    hours = max(1, ceil(duration_minutes / MINUTES_PER_HOUR))

    # Base time fee.
    if rate.tariff_mode == "flat":
        fee = rate.base_tariff or rate.hourly_rate
    elif rate.tariff_mode == "progressive":
        first_hour = rate.base_tariff or rate.hourly_rate
        fee = first_hour + max(0, hours - 1) * rate.hourly_rate
    else:
        per_hour = rate.hourly_rate or rate.base_tariff
        fee = hours * per_hour

    # Overnight surcharge.
    if rate.overnight_mode != "none" and rate.overnight_tariff > 0:
        if rate.overnight_mode == "24h":
            nights = int(duration_minutes // MINUTES_PER_DAY)
        else:  # "midnight": count calendar-date boundaries crossed
            nights = max(0, (exit_time.date() - entry_time.date()).days)
        fee += nights * rate.overnight_tariff

    # Per-day cap (applies per 24h block; 0 = no cap).
    if rate.daily_cap > 0:
        days = max(1, ceil(duration_minutes / MINUTES_PER_DAY))
        fee = min(fee, days * rate.daily_cap)

    # Lost-ticket penalty floor — applied after the cap so the denda is never
    # eroded by the per-day cap.
    if is_lost_ticket and rate.lost_ticket_penalty > 0:
        fee = max(fee, rate.lost_ticket_penalty)

    return fee


# Default configuration for development / first-time setup
DEFAULT_TARIFF_CONFIG = TariffConfig(
    vehicle_types={
        "MOTOR": VehicleTypeRate(hourly_rate=2000, daily_cap=15000),
        "MOBIL": VehicleTypeRate(hourly_rate=5000, daily_cap=50000),
    },
    grace_period_minutes=15,
)
