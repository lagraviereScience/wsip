"""Shared column helpers for ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from sqlalchemy import DateTime, func
from sqlalchemy.orm import mapped_column

# Every timestamp is timezone-aware and stored in UTC (DATABASE.md, "Conventions").
TimestampTZ = DateTime(timezone=True)

CreatedAt = Annotated[
    datetime, mapped_column(TimestampTZ, nullable=False, server_default=func.now())
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(TimestampTZ, nullable=False, server_default=func.now(), onupdate=func.now()),
]
