"""Schemas for holds, bookings, offers and policy settings."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from .catalog import SEAT_ID_PATTERN, PricesIn
from .common import Flexible


class HoldIn(BaseModel):
    showtime_id: str
    seats: list[str] = Field(min_length=1, max_length=20)

    @field_validator("seats")
    @classmethod
    def _seats(cls, v: list[str]) -> list[str]:
        out = sorted({s.strip().upper() for s in v})
        for s in out:
            if not SEAT_ID_PATTERN.match(s):
                raise ValueError(f"Invalid seat id '{s}'")
        return out


class HoldOut(Flexible):
    id: str
    showtime_id: str
    seats: list[str]
    expires_at: datetime
    status: str


class BookingIn(BaseModel):
    hold_id: str
    offer_code: str | None = Field(default=None, max_length=20)


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class BookingOut(Flexible):
    id: str
    reference: str
    status: str
    seats: list[dict]
    subtotal: float
    discount: float
    total: float


class OfferIn(BaseModel):
    code: str = Field(min_length=3, max_length=20, pattern="^[A-Z0-9]+$")
    title: str = Field(min_length=3, max_length=80)
    description: str = Field(default="", max_length=300)
    discount_type: str = Field(pattern="^(percent|fixed)$")
    discount_value: float = Field(gt=0, le=100000)
    min_booking_value: float = Field(default=0, ge=0)
    max_discount: float | None = Field(default=None, gt=0)
    start_date: datetime
    end_date: datetime
    usage_limit: int | None = Field(default=None, ge=1, description="Total redemptions across all customers")
    per_user_limit: int = Field(default=1, ge=1, le=100)
    is_active: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return str(v).strip().upper()

    @model_validator(mode="after")
    def _check(self) -> "OfferIn":
        if self.discount_type == "percent" and self.discount_value > 100:
            raise ValueError("Percentage discounts cannot exceed 100")
        if self.end_date <= self.start_date:
            raise ValueError("End date must be after the start date")
        return self


class OfferUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    discount_type: str | None = Field(default=None, pattern="^(percent|fixed)$")
    discount_value: float | None = Field(default=None, gt=0, le=100000)
    min_booking_value: float | None = Field(default=None, ge=0)
    max_discount: float | None = Field(default=None, ge=0, description="0 removes the cap")
    start_date: datetime | None = None
    end_date: datetime | None = None
    usage_limit: int | None = Field(default=None, ge=0, description="0 removes the limit")
    per_user_limit: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None


class OfferValidateIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    hold_id: str


class PolicyIn(BaseModel):
    hold_minutes: int = Field(ge=1, le=30)
    max_seats_per_booking: int = Field(ge=1, le=20)
    booking_cutoff_minutes: int = Field(ge=0, le=240)
    cancellations_enabled: bool
    cancellation_cutoff_hours: float = Field(ge=0, le=168)
    refund_percent: int = Field(ge=0, le=100)
    default_prices: PricesIn
    cleaning_buffer_minutes: int = Field(ge=0, le=120)
