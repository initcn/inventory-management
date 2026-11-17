"""
Simulated External Supplier System Integration Adapter (Module 8 / Section 8).

IMPORTANT DOCUMENTATION NOTE:
This module is a self-contained, local SIMULATED integration adapter designed to
demonstrate external system integration concepts (Adapter Pattern, payload
validation, success/failure responses, and timeout/unavailable service handling)
without requiring external API keys or live commercial vendor endpoints.
"""

from datetime import datetime
from typing import Any, Optional


class SupplierIntegrationError(RuntimeError):
    """Raised when the simulated external supplier endpoint times out or is unavailable."""

    def __init__(self, message: str, error_code: str = "SERVICE_UNAVAILABLE"):
        super().__init__(message)
        self.error_code = error_code


# Simulated external vendor catalog indexed by (supplier_code, sku)
SIMULATED_VENDOR_CATALOG: dict[tuple[str, str], dict[str, Any]] = {
    ("SUP-APEX-01", "MED-PARA-500"): {
        "vendor_sku": "APX-PCM-500",
        "unit_price": 45.00,
        "min_order_qty": 20,
        "lead_time_days": 3,
        "stock_status": "IN_STOCK",
        "available_vendor_qty": 2500,
    },
    ("SUP-APEX-01", "MED-AMOX-250"): {
        "vendor_sku": "APX-AMX-250",
        "unit_price": 92.00,
        "min_order_qty": 25,
        "lead_time_days": 4,
        "stock_status": "IN_STOCK",
        "available_vendor_qty": 1200,
    },
    ("SUP-BIO-02", "MED-INS-100"): {
        "vendor_sku": "BIO-INS-10ML",
        "unit_price": 440.00,
        "min_order_qty": 15,
        "lead_time_days": 2,
        "stock_status": "IN_STOCK",
        "available_vendor_qty": 600,
    },
    ("SUP-BIO-02", "MED-AZI-500"): {
        "vendor_sku": "BIO-AZI-500",
        "unit_price": 115.00,
        "min_order_qty": 30,
        "lead_time_days": 3,
        "stock_status": "IN_STOCK",
        "available_vendor_qty": 950,
    },
    ("SUP-SURG-03", "SURG-GLV-M"): {
        "vendor_sku": "NSS-GLV-MED",
        "unit_price": 100.00,
        "min_order_qty": 20,
        "lead_time_days": 2,
        "stock_status": "IN_STOCK",
        "available_vendor_qty": 1800,
    },
    ("SUP-SURG-03", "SURG-MASK-N95"): {
        "vendor_sku": "NSS-N95-PRO",
        "unit_price": 65.00,
        "min_order_qty": 50,
        "lead_time_days": 5,
        "stock_status": "LOW_STOCK",
        "available_vendor_qty": 150,
    },
    ("SUP-CHEM-04", "CHEM-ETH-500"): {
        "vendor_sku": "CHM-ETH-500ML",
        "unit_price": 175.00,
        "min_order_qty": 10,
        "lead_time_days": 4,
        "stock_status": "IN_STOCK",
        "available_vendor_qty": 800,
    },
    ("SUP-CHEM-04", "MED-ORS-20"): {
        "vendor_sku": "CHM-ORS-WHO",
        "unit_price": 18.00,
        "min_order_qty": 100,
        "lead_time_days": 3,
        "stock_status": "IN_STOCK",
        "available_vendor_qty": 5000,
    },
}


class SupplierIntegrationAdapter:
    """
    Isolated adapter that simulates communication with an external supplier ERP/portal.
    Supports controlled simulation modes:
      - 'SUCCESS': Normal catalog verification or PO dispatch acknowledgment.
      - 'FAILURE': Business-level rejection (e.g., unknown SKU, MOQ violation, out of stock).
      - 'TIMEOUT': Simulates a network gateway timeout (HTTP 504 / socket timeout).
      - 'UNAVAILABLE': Simulates an offline external supplier service (HTTP 503).
    """

    def verify_supplier_product(
        self,
        supplier_code: str,
        product_sku: str,
        requested_quantity: int = 20,
        simulation_mode: str = "SUCCESS",
    ) -> dict[str, Any]:
        """
        Query the simulated external supplier catalog to validate product availability,
        contract unit price (₹), minimum order quantity (MOQ), and lead time.
        """
        mode = (simulation_mode or "SUCCESS").strip().upper()
        sup_clean = (supplier_code or "").strip().upper()
        sku_clean = (product_sku or "").strip().upper()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if mode == "TIMEOUT":
            raise SupplierIntegrationError(
                f"Simulated gateway timeout (3000ms exceeded) while contacting supplier endpoint for '{sup_clean}'.",
                error_code="GATEWAY_TIMEOUT",
            )

        if mode == "UNAVAILABLE":
            raise SupplierIntegrationError(
                f"Simulated external supplier portal '{sup_clean}' is temporarily unavailable (HTTP 503).",
                error_code="SERVICE_UNAVAILABLE",
            )

        if mode == "FAILURE":
            return {
                "ok": False,
                "simulated": True,
                "status": "REJECTED_BY_SUPPLIER",
                "supplier_code": sup_clean,
                "product_sku": sku_clean,
                "requested_quantity": int(requested_quantity),
                "timestamp": timestamp,
                "message": (
                    f"Simulated failure response: SKU '{sku_clean}' is currently backordered "
                    f"or discontinued at supplier '{sup_clean}'."
                ),
            }

        catalog_entry: Optional[dict[str, Any]] = SIMULATED_VENDOR_CATALOG.get(
            (sup_clean, sku_clean)
        )
        if not catalog_entry:
            # Fallback deterministic mock response for any custom user-created supplier/SKU pair
            catalog_entry = {
                "vendor_sku": f"EXT-{sku_clean}",
                "unit_price": 110.00,
                "min_order_qty": 10,
                "lead_time_days": 4,
                "stock_status": "IN_STOCK",
                "available_vendor_qty": 500,
            }

        req_qty = int(requested_quantity)
        moq = int(catalog_entry["min_order_qty"])
        avail_qty = int(catalog_entry["available_vendor_qty"])

        if req_qty < moq:
            return {
                "ok": False,
                "simulated": True,
                "status": "MOQ_VIOLATION",
                "supplier_code": sup_clean,
                "product_sku": sku_clean,
                "vendor_sku": catalog_entry["vendor_sku"],
                "requested_quantity": req_qty,
                "min_order_qty": moq,
                "unit_price": catalog_entry["unit_price"],
                "lead_time_days": catalog_entry["lead_time_days"],
                "timestamp": timestamp,
                "message": (
                    f"Requested quantity ({req_qty}) is below supplier minimum order quantity "
                    f"(MOQ: {moq} units)."
                ),
            }

        if req_qty > avail_qty:
            return {
                "ok": False,
                "simulated": True,
                "status": "INSUFFICIENT_VENDOR_STOCK",
                "supplier_code": sup_clean,
                "product_sku": sku_clean,
                "vendor_sku": catalog_entry["vendor_sku"],
                "requested_quantity": req_qty,
                "available_vendor_qty": avail_qty,
                "unit_price": catalog_entry["unit_price"],
                "lead_time_days": catalog_entry["lead_time_days"],
                "timestamp": timestamp,
                "message": (
                    f"Requested quantity ({req_qty}) exceeds supplier available allocation "
                    f"({avail_qty} units)."
                ),
            }

        return {
            "ok": True,
            "simulated": True,
            "status": "VERIFIED",
            "supplier_code": sup_clean,
            "product_sku": sku_clean,
            "vendor_sku": catalog_entry["vendor_sku"],
            "requested_quantity": req_qty,
            "min_order_qty": moq,
            "available_vendor_qty": avail_qty,
            "unit_price": catalog_entry["unit_price"],
            "estimated_total": round(req_qty * float(catalog_entry["unit_price"]), 2),
            "lead_time_days": catalog_entry["lead_time_days"],
            "stock_status": catalog_entry["stock_status"],
            "ack_reference": f"SIM-ACK-{sup_clean}-{sku_clean}",
            "timestamp": timestamp,
            "message": (
                f"Simulated supplier verification succeeded: {req_qty} units of '{sku_clean}' "
                f"available @ ₹{catalog_entry['unit_price']:.2f}/unit "
                f"(Lead time: {catalog_entry['lead_time_days']} days)."
            ),
        }
