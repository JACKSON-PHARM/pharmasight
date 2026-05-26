"""Platform usage telemetry helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ["DEBUG"] = "false"

from app.services.platform_usage_service import endpoint_group_for_path  # noqa: E402


def test_endpoint_group_for_nested_api_path():
    assert endpoint_group_for_path("/api/sales/invoices/123/payments") == "/api/sales/invoices"


def test_endpoint_group_for_top_level_api_path():
    assert endpoint_group_for_path("/api/config") == "/api/config"
