"""Pre-defined what-if scenario templates (fictional; for demonstration)."""
from __future__ import annotations

TEMPLATES = [
    {"scenario_name": "baseline", "disturbances": {}},
    {"scenario_name": "wet pellets (+3 % moisture)", "disturbances": {"pellet_moisture_wt_pct": 4.5}},
    {"scenario_name": "low-reactivity coal (-20 %)", "disturbances": {"gasification_multiplier": 0.8}},
    {"scenario_name": "refractory wear 40 %", "disturbances": {"refractory_wear_fraction": 0.4}},
    {"scenario_name": "feed-end air leak +1500 Nm3/h", "disturbances": {"air_leak_feed_end_nm3h": 1900}},
    {"scenario_name": "throughput +5 %", "feed": {"pellet_feed_tph": None}, "scale_pellet": 1.05},
    {"scenario_name": "ring 0.15 m (what-if)", "disturbances": {"accretion_thickness_m": 0.15}},
]
