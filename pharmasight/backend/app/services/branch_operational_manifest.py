"""
Compiled branch operational truth — single runtime view of clinical stations.

Phase 1.5 (no persistence): three explicit inputs compiled into one contract:
  A. Governance — company_modules (capabilities)
  B. Operational — declared station registry (workstation mode, routing)
  C. Inventory linkage — department_stores (optional, by store code)

The compiler is the truth engine; UI must not re-derive meaning.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.clinic import DepartmentStore
from app.models.company import Branch
from app.services.company_governance_service import is_module_enabled_compiled

# Declared station registry (product contract — not inferred from module names).
# workstation_mode: active_workstation | routing_only
# routing_code matches encounters.initial_destination (lowercase).
STATION_REGISTRY_VERSION = "2026-05-15"

STATION_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "code": "TRIAGE",
        "routing_code": "triage",
        "name": "Triage",
        "workstation_mode": "active_workstation",
        "module_required": "clinic",
        "participates_in_routing": True,
        "inventory_store_codes": ("TRIAGE",),
    },
    {
        "code": "CONSULTATION",
        "routing_code": "consultation",
        "name": "Consultation",
        "workstation_mode": "active_workstation",
        "module_required": "clinic",
        "participates_in_routing": True,
        "inventory_store_codes": (),
    },
    {
        "code": "PHARMACY",
        "routing_code": "pharmacy",
        "name": "Pharmacy",
        "workstation_mode": "routing_only",
        "module_required": "pharmacy",
        "participates_in_routing": True,
        "inventory_store_codes": (),
    },
    {
        "code": "LAB",
        "routing_code": "lab",
        "name": "Lab",
        "workstation_mode": "routing_only",
        "module_required": "lab",
        "participates_in_routing": True,
        "inventory_store_codes": ("LAB",),
    },
    {
        "code": "RADIOLOGY",
        "routing_code": "radiology",
        "name": "Radiology",
        "workstation_mode": "routing_only",
        "module_required": "radiology",
        "participates_in_routing": True,
        "inventory_store_codes": (),
    },
    {
        "code": "PROCEDURE",
        "routing_code": "procedure",
        "name": "Procedure",
        "workstation_mode": "routing_only",
        "module_required": "clinic",
        "participates_in_routing": True,
        "inventory_store_codes": (),
    },
    {
        "code": "REFERRAL",
        "routing_code": "referral",
        "name": "Referral",
        "workstation_mode": "routing_only",
        "module_required": "clinic",
        "participates_in_routing": True,
        "inventory_store_codes": (),
    },
)

# Why a station ended up in its operational status (stable codes for UI + admin debug).
REASON_MODULE_NOT_LICENSED = "module_not_licensed"
REASON_WORKSTATION_READY = "workstation_ready_in_registry"
REASON_MODULE_ENABLED_WORKSTATION_NOT_READY = "module_enabled_workstation_not_ready_in_registry"
REASON_NOT_PARTICIPATING_IN_ROUTING = "not_participating_in_routing"


def _registry_modules() -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for spec in STATION_REGISTRY:
        mod = spec.get("module_required")
        if mod and mod not in seen:
            seen.add(mod)
            out.append(mod)
    return out


def _stores_by_code(db: Session, company_id: UUID, branch_id: UUID) -> Dict[str, DepartmentStore]:
    rows = (
        db.query(DepartmentStore)
        .filter(
            DepartmentStore.company_id == company_id,
            DepartmentStore.branch_id == branch_id,
            DepartmentStore.is_active.is_(True),
        )
        .all()
    )
    out: Dict[str, DepartmentStore] = {}
    for r in rows:
        key = (r.code or "").strip().upper()
        if key:
            out[key] = r
    return out


def _resolve_inventory(
    spec: dict[str, Any], stores: Dict[str, DepartmentStore]
) -> Tuple[Optional[DepartmentStore], Optional[str]]:
    for sc in spec.get("inventory_store_codes") or ():
        key = str(sc).strip().upper()
        row = stores.get(key)
        if row:
            return row, key
    return None, None


def _derive_operational(
    spec: dict[str, Any], *, module_enabled: bool
) -> Tuple[dict[str, Any], List[str]]:
    """Operational reality from registry + governance. Returns (operational, rules)."""
    rules: List[str] = []
    participates = bool(spec.get("participates_in_routing"))
    ws_mode = spec.get("workstation_mode") or "routing_only"
    rules.append(f"registry.workstation_mode={ws_mode}")
    rules.append(f"registry.participates_in_routing={participates}")

    if not participates:
        return (
            {
                "status": "off",
                "status_label": "Not routable",
                "type": "unavailable",
                "activation_reason": REASON_NOT_PARTICIPATING_IN_ROUTING,
                "workstation": False,
                "selectable_for_intake": False,
                "participates_in_routing": False,
            },
            rules,
        )

    if not module_enabled:
        rules.append(f"governance.module {spec.get('module_required')} enabled=false")
        return (
            {
                "status": "off",
                "status_label": "Not licensed",
                "type": "unavailable",
                "activation_reason": REASON_MODULE_NOT_LICENSED,
                "workstation": False,
                "selectable_for_intake": False,
                "participates_in_routing": participates,
            },
            rules,
        )

    rules.append(f"governance.module {spec.get('module_required')} enabled=true")

    if ws_mode == "active_workstation":
        rules.append("operational=active (registry declares active_workstation)")
        return (
            {
                "status": "active",
                "status_label": "Operational",
                "type": "routing_and_workstation",
                "activation_reason": REASON_WORKSTATION_READY,
                "workstation": True,
                "selectable_for_intake": True,
                "participates_in_routing": participates,
            },
            rules,
        )

    rules.append("operational=routing_only (registry declares routing_only)")
    return (
        {
            "status": "routing_only",
            "status_label": "Routing only",
            "type": "routing_only",
            "activation_reason": REASON_MODULE_ENABLED_WORKSTATION_NOT_READY,
            "workstation": False,
            "selectable_for_intake": True,
            "participates_in_routing": participates,
        },
        rules,
    )


def _compile_station(
    spec: dict[str, Any],
    *,
    company_id: UUID,
    db: Session,
    stores: Dict[str, DepartmentStore],
    module_enabled_map: Dict[str, bool],
    include_debug: bool,
) -> Dict[str, Any]:
    module_required = spec.get("module_required")
    module_enabled = module_enabled_map.get(module_required, True) if module_required else True

    store_row, linked_code = _resolve_inventory(spec, stores)
    operational, rules = _derive_operational(spec, module_enabled=module_enabled)

    inventory_rules: List[str] = []
    if linked_code and store_row:
        inventory_rules.append(
            f"inventory.store_code {linked_code} matched department_store id={store_row.id}"
        )
    elif spec.get("inventory_store_codes"):
        inventory_rules.append(
            f"inventory.store_codes {list(spec.get('inventory_store_codes'))} — no active branch store"
        )
    else:
        inventory_rules.append("inventory.no_store_codes_in_registry")

    has_stock = store_row is not None and module_enabled

    station: Dict[str, Any] = {
        "code": spec["code"],
        "routing_code": spec["routing_code"],
        "name": spec["name"],
        "registry": {
            "workstation_mode": spec.get("workstation_mode"),
            "module_required": module_required,
            "inventory_store_codes": list(spec.get("inventory_store_codes") or ()),
            "participates_in_routing": bool(spec.get("participates_in_routing")),
        },
        "governance": {
            "module_required": module_required,
            "module_enabled": module_enabled,
        },
        "inventory": {
            "stock": has_stock,
            "department_store_id": str(store_row.id) if store_row else None,
            "linked_store_code": linked_code,
        },
        "operational": operational,
    }

    if include_debug:
        station["derivation"] = {
            "rules_applied": rules + inventory_rules,
            "registry_version": STATION_REGISTRY_VERSION,
        }

    return station


def _build_governance_snapshot(
    db: Session, company_id: UUID, module_keys: List[str]
) -> Dict[str, Any]:
    modules = {key: is_module_enabled_compiled(db, company_id, key) for key in module_keys}
    return {
        "source": "company_modules",
        "modules_evaluated": module_keys,
        "modules_enabled": [k for k, v in modules.items() if v],
        "modules": modules,
    }


def _build_inventory_linkage(
    stores: Dict[str, DepartmentStore], stations: List[Dict[str, Any]]
) -> Dict[str, Any]:
    by_code: Dict[str, Any] = {}
    for code, row in stores.items():
        by_code[code] = {
            "department_store_id": str(row.id),
            "name": getattr(row, "name", None),
            "code": getattr(row, "code", None),
        }
    linked: List[Dict[str, Any]] = []
    for st in stations:
        inv = st.get("inventory") or {}
        lid = inv.get("department_store_id")
        lcode = inv.get("linked_store_code")
        if lid and lcode:
            linked.append(
                {
                    "station_code": st["code"],
                    "store_code": lcode,
                    "department_store_id": lid,
                }
            )
    registry_codes = set()
    for spec in STATION_REGISTRY:
        for c in spec.get("inventory_store_codes") or ():
            registry_codes.add(str(c).strip().upper())
    unlinked = sorted(registry_codes - set(by_code.keys()))
    return {
        "source": "department_stores",
        "stores_by_code": by_code,
        "station_links": linked,
        "registry_store_codes_without_branch_store": unlinked,
    }


def compile_branch_operational_manifest(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    branch_name: Optional[str] = None,
    include_debug: bool = False,
) -> Dict[str, Any]:
    """
    Compiled branch operational truth (read-only, no new tables).
    """
    branch = db.query(Branch).filter(Branch.id == branch_id, Branch.company_id == company_id).first()
    if not branch:
        raise ValueError("Branch not found")

    module_keys = _registry_modules()
    governance = _build_governance_snapshot(db, company_id, module_keys)
    module_enabled_map = governance["modules"]

    stores = _stores_by_code(db, company_id, branch_id)
    stations = [
        _compile_station(
            spec,
            company_id=company_id,
            db=db,
            stores=stores,
            module_enabled_map=module_enabled_map,
            include_debug=include_debug,
        )
        for spec in STATION_REGISTRY
    ]

    routing_stations = [
        s for s in stations if (s.get("operational") or {}).get("selectable_for_intake")
    ]

    payload: Dict[str, Any] = {
        "contract": "compiled_branch_operational_truth",
        "branch_id": str(branch_id),
        "branch_name": branch_name or branch.name,
        "company_id": str(company_id),
        "manifest_version": "phase1.5-compiled",
        "governance": governance,
        "station_registry": {
            "version": STATION_REGISTRY_VERSION,
            "declared_stations": [
                {
                    "code": s["code"],
                    "routing_code": s["routing_code"],
                    "name": s["name"],
                    "workstation_mode": s["workstation_mode"],
                    "module_required": s.get("module_required"),
                    "inventory_store_codes": list(s.get("inventory_store_codes") or ()),
                }
                for s in STATION_REGISTRY
            ],
        },
        "inventory_linkage": _build_inventory_linkage(stores, stations),
        "stations": stations,
        "routing_stations": routing_stations,
    }

    if include_debug:
        payload["debug"] = {
            "compiler": "branch_operational_manifest",
            "inputs": ["company_modules", "department_stores", "STATION_REGISTRY"],
            "station_count": len(stations),
            "routing_station_count": len(routing_stations),
        }

    return payload
