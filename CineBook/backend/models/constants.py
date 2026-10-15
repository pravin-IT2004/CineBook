"""Domain constants shared by services and schemas."""
from __future__ import annotations


class Role:
    CUSTOMER = "customer"
    ADMIN = "admin"
    ALL = (CUSTOMER, ADMIN)


class BookingStatus:
    PENDING = "pending"  # being processed (seats being converted)
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ALL = (PENDING, CONFIRMED, CANCELLED, FAILED)

    # Allowed state transitions (enforced by atomic conditional updates)
    TRANSITIONS = {
        PENDING: {CONFIRMED, FAILED},
        CONFIRMED: {CANCELLED},
        CANCELLED: set(),
        FAILED: set(),
    }


class HoldStatus:
    ACTIVE = "active"
    CONVERTED = "converted"
    RELEASED = "released"
    EXPIRED = "expired"


class LockState:
    HELD = "held"
    BOOKED = "booked"


class MovieStatus:
    NOW_SHOWING = "now_showing"
    COMING_SOON = "coming_soon"
    ARCHIVED = "archived"
    ALL = (NOW_SHOWING, COMING_SOON, ARCHIVED)
    LABELS = {NOW_SHOWING: "Now Showing", COMING_SOON: "Coming Soon", ARCHIVED: "Archived"}


SEAT_CATEGORIES = ("regular", "premium", "recliner")
SCREEN_TYPES = ("2D", "3D", "IMAX", "4DX", "Dolby Atmos")
CERTIFICATES = ("U", "UA", "UA 7+", "UA 13+", "UA 16+", "A", "S")

DEFAULT_POLICY = {
    "hold_minutes": 5,
    "max_seats_per_booking": 10,
    "booking_cutoff_minutes": 10,  # online booking closes this many minutes before showtime
    "cancellations_enabled": True,
    "cancellation_cutoff_hours": 2,  # cannot cancel within this many hours of showtime
    "refund_percent": 80,  # simulated refund percentage
    "default_prices": {"regular": 180.0, "premium": 260.0, "recliner": 420.0},
    "cleaning_buffer_minutes": 20,  # gap enforced between shows on the same screen
}
