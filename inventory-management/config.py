import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    """Application configuration for Inventory & Multi-Warehouse Management System."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "sdp-group12-inventory-secret-key")
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", str(BASE_DIR / "inventory.db")
    )
    SCHEMA_PATH = str(BASE_DIR / "schema.sql")
    NEAR_EXPIRY_DAYS = int(os.environ.get("NEAR_EXPIRY_DAYS", "30"))
    CURRENCY_SYMBOL = "₹"
