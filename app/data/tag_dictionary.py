"""Typed tag registry (logical tag identifiers - examples, NOT claims about any
site's installed instrumentation).  Exported to docs/DATA_DICTIONARY.csv."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Tag:
    tag_id: str
    human_name: str
    source_system: str
    data_type: str
    engineering_unit: str
    raw_unit: str
    conversion: str
    valid_min: float
    valid_max: float
    sampling_period_s: float
    physical_location_z_m: float | None
    phase: str
    source_quality: str  # measured | derived | inferred
    timestamp_timezone: str
    expected_latency_s: float
    calibration_date: str
    read_permission: str
    commandable_flag: bool
    owner: str
    equipment_id: str
    notes: str


def _t(tag_id, name, unit, lo, hi, period, z=None, phase="process", src="DCS", quality="measured", lat=5,
       cmd=False, eq="RK-01", notes="", raw=None, conv="1:1"):
    return Tag(tag_id, name, src, "float", unit, raw or unit, conv, lo, hi, period, z, phase, quality, "UTC", lat,
               "SITE-PENDING", "viewer+", cmd, "process_engineer", eq, notes)


def build_registry(cfg=None) -> list[Tag]:
    L = cfg.geometry.length_m if cfg else 42.0
    tubes = cfg.air.secondary_tubes if cfg else []
    tags = [
        _t("PELLET_FEED_TPH", "Pellet weigh-feeder rate", "t/h", 0, 120, 10, 0.0, "solid", eq="WF-PEL",
           notes="setpoint is commandable at site only via local loop"),
        _t("COAL_FEED_TPH", "Feed-end coal weigh-feeder rate", "t/h", 0, 100, 10, 0.0, "solid", eq="WF-CF"),
        _t("COAL_INJECTION_TPH", "Discharge-end injection coal rate", "t/h", 0, 60, 10, L, "solid", eq="WF-CI"),
        _t("DOLOMITE_TPH", "Dolomite feeder rate", "t/h", 0, 10, 10, 0.0, "solid", eq="WF-DOL"),
        _t("KILN_RPM", "Kiln rotational speed", "rev/min", 0, 3, 5, None, "mechanical", eq="DRV-01"),
        _t("KILN_DRIVE_TORQUE", "Kiln main-drive torque", "% rated", 0, 150, 5, None, "mechanical", eq="DRV-01"),
        _t("KILN_DRAFT_PA", "Feed-end hood draft", "Pa", -600, 100, 2, 0.0, "gas", eq="HOOD-F"),
        _t("AIR_PRIMARY_NM3H", "Primary / central burner air", "Nm3/h", 0, 60000, 5, L, "gas", eq="FAN-PA"),
        _t("EXHAUST_CO_VOLPCT_DRY", "Kiln exit CO (dry)", "vol % dry", 0, 30, 10, 0.0, "gas", src="ANALYSER", lat=90,
           notes="sample-conditioned extractive analyser; transport delay modelled"),
        _t("EXHAUST_CO2_VOLPCT_DRY", "Kiln exit CO2 (dry)", "vol % dry", 0, 40, 10, 0.0, "gas", src="ANALYSER", lat=90),
        _t("EXHAUST_O2_VOLPCT_DRY", "Kiln exit O2 (dry)", "vol % dry", 0, 21, 10, 0.0, "gas", src="ANALYSER", lat=90),
        _t("EXHAUST_TEMP_C", "Kiln exit gas temperature", "C", 0, 1400, 5, 0.0, "gas"),
        _t("COOLER_EXIT_C", "Cooler product discharge temperature", "C", 0, 400, 30, None, "solid", eq="CLR-01"),
        _t("DRI_DISCHARGE_TPH", "DRI to product conveyor (belt scale)", "t/h", 0, 100, 30, None, "solid", eq="BS-DRI"),
        _t("WHRB_STEAM_TPH", "WHRB steam flow", "t/h", 0, 200, 10, None, "utility", eq="WHRB-01"),
        _t("ESP_DP_PA", "ESP inlet-outlet differential pressure", "Pa", 0, 3000, 10, None, "gas", eq="ESP-01"),
        _t("LAB_METALLIZATION_PCT", "Lab metallization of DRI sample", "%", 50, 100, 7200, None, "solid", src="LIMS",
           lat=5400, notes="manual sample every ~2 h; analysis delay ~1.5 h; RTD cohort alignment required"),
        _t("LAB_TOTAL_FE_PCT", "Lab total Fe", "wt %", 60, 99, 7200, None, "solid", src="LIMS", lat=5400),
        _t("LAB_METALLIC_FE_PCT", "Lab metallic Fe", "wt %", 40, 99, 7200, None, "solid", src="LIMS", lat=5400),
        _t("LAB_DRI_CARBON_PCT", "Lab DRI carbon", "wt %", 0, 3, 7200, None, "solid", src="LIMS", lat=5400),
    ]
    for i, frac in enumerate([0.1, 0.25, 0.4, 0.55, 0.7, 0.85]):
        z = round(frac * L, 2)
        tags.append(_t(f"TEMP_FREEBOARD_Z{i+1}_C", f"Freeboard thermocouple zone {i+1}", "C", 0, 1500, 5, z, "gas",
                       notes="TC through shell into freeboard; reading lies between gas and bed T (bias modelled)"))
        tags.append(_t(f"TEMP_SHELL_Z{i+1}_C", f"Shell scanner zone {i+1} (mean)", "C", 0, 600, 10, z, "shell",
                       src="IR-SCANNER"))
    for t in tubes:
        tags.append(_t(f"AIR_SECONDARY_{t.tube_id}_NM3H", f"Secondary air tube {t.tube_id}", "Nm3/h", 0, t.max_nm3h, 5,
                       t.z_m, "gas", eq=f"FAN-{t.tube_id}"))
    derived = [
        ("EST_METALLIZATION_PCT", "Model-estimated discharge metallization", "%", 0, 100, "inferred"),
        ("EST_PEAK_BED_T_C", "Model-estimated peak bed temperature", "C", 0, 1500, "inferred"),
        ("EST_GAS_REDUCING_POTENTIAL", "Model-estimated CO/(CO+CO2) in bed", "-", 0, 1, "inferred"),
        ("EST_ACCRETION_RISK", "Accretion risk proxy (unvalidated)", "-", 0, 1, "inferred"),
        ("CALC_SPECIFIC_COAL_KG_T", "Specific coal per t DRI", "kg/t", 0, 3000, "derived"),
    ]
    for tid, nm, u, lo, hi, q in derived:
        tags.append(Tag(tid, nm, "TWIN", "float", u, u, "n/a", lo, hi, 60, None, "model", q, "UTC", 60, "n/a",
                        "viewer+", False, "data_scientist", "TWIN", "never written to DCS"))
    return tags


def export_csv(path: Path, cfg=None):
    rows = build_registry(cfg)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[fl.name for fl in fields(Tag)])
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))
    return len(rows)
