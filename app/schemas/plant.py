"""Schema-validated plant configuration (units in field names; plausibility guards).

All numbers in fixtures are explicitly FICTIONAL demonstration values for an
anonymised plant "Industry-X".  They are configuration inputs, not plant facts.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Provenance = Literal["SYNTHETIC-DEMO", "MEASURED", "CALIBRATED", "INFERRED", "PLACEHOLDER", "DESIGN"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlantMeta(_M):
    plant_id: str = "industry-x-rk1"
    name: str = "Industry-X Rotary Kiln #1 (synthetic demo)"
    config_version: str = "plant-demo-v1"
    preset: str = "RK-100TPD"
    site_timezone: str = "Asia/Kolkata"
    provenance: Provenance = "SYNTHETIC-DEMO"


class Geometry(_M):
    length_m: float = Field(42.0, ge=10, le=150)
    shell_diameter_m: float = Field(3.0, ge=1.2, le=7.0)
    slope_pct: float = Field(2.5, ge=0.5, le=6.0)
    rpm: float = Field(0.42, ge=0.05, le=3.0)
    rpm_min: float = Field(0.2, ge=0.0, le=3.0)
    rpm_max: float = Field(1.0, ge=0.1, le=3.0)
    discharge_dam_height_m: float = Field(0.45, ge=0.0, le=1.5)
    dynamic_repose_angle_deg: float = Field(36.0, ge=20, le=50)
    wall_emissivity: float = Field(0.85, ge=0.3, le=1.0)
    bed_emissivity: float = Field(0.90, ge=0.3, le=1.0)
    accretion_thickness_m: float = Field(0.0, ge=0.0, le=0.6, description="uniform ring layer, what-if only")
    provenance: Provenance = "SYNTHETIC-DEMO"


class RefractoryLayer(_M):
    name: str
    thickness_m: float = Field(..., ge=0.0, le=0.6)
    k_W_mK: float = Field(..., gt=0.02, le=50)
    k_T_coeff_per_K: float = Field(0.0, ge=-1e-3, le=2e-3, description="k(T)=k*(1+c*(T-298))")
    rho_kg_m3: float = Field(..., ge=200, le=4000)
    cp_J_kgK: float = Field(..., ge=400, le=2000)
    nodes: int = Field(3, ge=1, le=8)


class Lining(_M):
    layers: list[RefractoryLayer] = [
        RefractoryLayer(name="high-alumina castable (working)", thickness_m=0.200, k_W_mK=1.50, k_T_coeff_per_K=-1.0e-4,
                        rho_kg_m3=2450, cp_J_kgK=1000, nodes=4),
        RefractoryLayer(name="insulating castable", thickness_m=0.030, k_W_mK=0.35, k_T_coeff_per_K=2.0e-4,
                        rho_kg_m3=1100, cp_J_kgK=950, nodes=1),
    ]
    shell_thickness_m: float = Field(0.025, ge=0.008, le=0.08)
    shell_k_W_mK: float = Field(45.0, ge=10, le=60)
    shell_rho_kg_m3: float = 7850.0
    shell_cp_J_kgK: float = 500.0
    shell_emissivity: float = Field(0.80, ge=0.2, le=1.0)
    wear_fraction: float = Field(0.0, ge=0.0, le=0.8, description="fractional loss of working-lining thickness")
    provenance: Provenance = "SYNTHETIC-DEMO"


class PelletFeed(_M):
    feed_tph: float = Field(6.8, ge=0.0, le=120)
    assay_dry_wt_pct: dict = {"Fe_total": 64.5, "FeO": 0.8, "SiO2": 3.4, "Al2O3": 2.1, "CaO": 0.6, "MgO": 0.25,
                              "TiO2": 0.10, "P": 0.05, "S": 0.01, "LOI": 0.4}
    moisture_wt_pct: float = Field(1.5, ge=0, le=12)
    diameter_mm: float = Field(12.0, ge=5, le=25)
    porosity: float = Field(0.27, ge=0.05, le=0.5)
    apparent_density_kg_m3: float = Field(3650, ge=2500, le=5000)
    bulk_density_kg_m3: float = Field(2050, ge=1200, le=3000)
    tortuosity: float = Field(3.0, ge=1.2, le=8)
    abrasion_index_pct: float = Field(4.0, ge=0, le=15)
    swelling_index_pct: float = Field(12.0, ge=0, le=40)
    crushing_strength_daN: float = Field(250, ge=50, le=500)
    lot_id: str = "PEL-LOT-DEMO-01"
    provenance: Provenance = "SYNTHETIC-DEMO"


class CoalAssay(_M):
    proximate_ar_wt_pct: dict = {"fixed_carbon": 42.0, "volatile_matter": 27.0, "ash": 23.0, "moisture": 8.0}
    ultimate_daf_wt_pct: dict = {"C": 79.5, "H": 5.0, "O": 13.1, "N": 1.7, "S": 0.7}
    ncv_MJ_kg_ar: float | None = Field(20.9, ge=8, le=33)
    gcv_MJ_kg_ar: float | None = None
    ash_oxides_wt_pct: dict = {"SiO2": 58.0, "Al2O3": 27.0, "Fe2O3_ash": 6.0, "CaO": 2.5, "MgO": 1.5, "TiO2": 1.5}
    ash_initial_deformation_C: float = Field(1250.0, ge=900, le=1600)
    reactivity_factor: float = Field(1.0, ge=0.2, le=5.0, description="relative char reactivity (CRI-scaled)")
    size_mm: float = Field(8.0, ge=1, le=30)
    bulk_density_kg_m3: float = Field(800, ge=500, le=1100)
    provenance: Provenance = "SYNTHETIC-DEMO"


class CoalStreams(_M):
    feed_coal_tph: float = Field(3.9, ge=0, le=100)
    injection_coal_tph: float = Field(1.5, ge=0, le=60)
    injection_throw_min_m: float = Field(3.0, ge=0, le=60)
    injection_throw_max_m: float = Field(16.0, ge=0.5, le=80)
    feed_coal: CoalAssay = CoalAssay()
    injection_coal: CoalAssay = CoalAssay()


class FluxRecycle(_M):
    dolomite_tph: float = Field(0.20, ge=0, le=10)
    dolomite_wt_pct: dict = {"CaCO3": 55.0, "MgCO3": 40.0, "SiO2": 5.0}
    dolomite_moisture_pct: float = Field(1.0, ge=0, le=10)
    recycle_char_tph: float = Field(0.0, ge=0, le=10)
    recycle_char_C_pct: float = Field(45.0, ge=0, le=95)
    provenance: Provenance = "SYNTHETIC-DEMO"


class AirTube(_M):
    tube_id: str
    z_m: float = Field(..., ge=0)
    flow_nm3h: float = Field(..., ge=0, le=60000)
    max_nm3h: float = Field(6000, ge=0, le=60000)
    available: bool = True


class AirSystem(_M):
    primary_air_nm3h: float = Field(400.0, ge=0, le=60000)
    injection_carrier_air_nm3h: float = Field(500.0, ge=0, le=30000)
    air_temperature_C: float = Field(35.0, ge=-20, le=600)
    ambient_temperature_C: float = Field(32.0, ge=-30, le=55)
    relative_humidity_pct: float = Field(60.0, ge=0, le=100)
    wind_speed_m_s: float = Field(1.5, ge=0, le=20)
    secondary_tubes: list[AirTube] = []
    leak_feed_end_nm3h: float = Field(400.0, ge=0, le=20000)
    leak_discharge_end_nm3h: float = Field(300.0, ge=0, le=20000)
    freeboard_mixing_efficiency: float = Field(0.80, ge=0.1, le=1.0)
    provenance: Provenance = "SYNTHETIC-DEMO"


class OffGasTrain(_M):
    kiln_feed_end_draft_Pa: float = Field(-40.0, ge=-500, le=50)
    dsc_capture_efficiency: float = Field(0.55, ge=0, le=1)
    abc_target_O2_dry_pct: float = Field(4.0, ge=0.5, le=12)
    abc_heat_loss_frac: float = Field(0.04, ge=0, le=0.3)
    abc_co_slip_frac: float = Field(0.002, ge=0, le=0.1)
    whrb_enabled: bool = True
    whrb_exit_gas_C: float = Field(190.0, ge=120, le=400)
    whrb_efficiency: float = Field(0.92, ge=0.5, le=1.0)
    steam_enthalpy_rise_kJ_kg: float = Field(2900.0, ge=1500, le=3300, description="feedwater -> superheated steam")
    steam_to_power_kg_per_kWh: float = Field(4.6, ge=3, le=8)
    esp_efficiency: float = Field(0.995, ge=0.8, le=0.9999)
    idfan_efficiency: float = Field(0.72, ge=0.3, le=0.9)
    idfan_pressure_rise_Pa: float = Field(4500.0, ge=500, le=12000)
    provenance: Provenance = "SYNTHETIC-DEMO"


class Cooler(_M):
    length_m: float = Field(30.0, ge=5, le=80)
    diameter_m: float = Field(2.2, ge=0.8, le=5)
    UA_kW_K: float = Field(14.0, ge=0.5, le=200)
    water_inlet_C: float = Field(32.0, ge=5, le=60)
    water_flow_m3h: float = Field(90.0, ge=1, le=1000)
    O2_ingress_nm3h: float = Field(0.0, ge=0, le=500)
    provenance: Provenance = "SYNTHETIC-DEMO"


class Separation(_M):
    char_to_magnetic_frac: float = Field(0.012, ge=0, le=0.2)
    ash_to_magnetic_frac: float = Field(0.02, ge=0, le=0.3)
    dri_to_nonmagnetic_frac: float = Field(0.008, ge=0, le=0.1)
    fines_threshold_mm: float = Field(3.0, ge=1, le=6)


class Kinetics(_M):
    """Demo kinetic parameters (CALIBRATION_REQUIRED).  k(T)=k0*exp(-E/RT)."""
    k0_hem_CO_m_s: float = 60.0
    E_hem_CO_J_mol: float = 60000.0
    k0_mag_CO_m_s: float = 25.0
    E_mag_CO_J_mol: float = 65000.0
    k0_wus_CO_m_s: float = 6.8
    E_wus_CO_J_mol: float = 69000.0
    h2_rate_factor: float = Field(3.0, ge=0.5, le=20)
    reduction_multiplier: float = Field(1.0, ge=0.1, le=10)
    product_layer_porosity: float = Field(0.50, ge=0.1, le=0.85)
    sherwood: float = Field(2.0, ge=2.0, le=50)
    boudouard_A_per_s_atm: float = 4.8e4
    boudouard_E_J_mol: float = 200000.0
    boudouard_K_CO_per_atm: float = 2.0
    gasification_multiplier: float = Field(1.0, ge=0.05, le=10)
    reverse_boudouard_factor: float = Field(0.05, ge=0, le=1)
    steam_gasif_factor: float = Field(3.0, ge=0, le=20)
    devol_A_per_s: float = 5.7e4
    devol_E_J_mol: float = 100000.0
    evap_A_per_s: float = 5.0e3
    evap_E_J_mol: float = 40700.0
    calc_ca_A_per_s: float = 1.03e5
    calc_ca_E_J_mol: float = 180000.0
    calc_mg_A_per_s: float = 1.1e5
    calc_mg_E_J_mol: float = 150000.0
    h2s_capture_efficiency: float = Field(0.55, ge=0, le=1)
    fes_pickup_frac: float = Field(0.12, ge=0, le=1)
    vm_O_to_CO_frac: float | None = Field(None, ge=0, le=1, description="None = auto (near-thermoneutral devolatilisation)")
    dust_entrainment_coeff: float = Field(2.0e-7, ge=0, le=1e-4)
    provenance: Provenance = "PLACEHOLDER"


class HeatTransfer(_M):
    h_gs_multiplier: float = Field(1.0, ge=0.1, le=10)
    h_gw_multiplier: float = Field(1.0, ge=0.1, le=10)
    h_cw_multiplier: float = Field(1.0, ge=0.1, le=10)
    shell_loss_multiplier: float = Field(1.0, ge=0.2, le=5)
    gas_absorption_coeff_per_atm_m: float = Field(1.1, ge=0.1, le=5)
    particle_absorption_coeff_per_m: float = Field(0.12, ge=0, le=2)
    bed_conductivity_W_mK: float = Field(0.40, ge=0.05, le=3)
    provenance: Provenance = "PLACEHOLDER"


class Numerics(_M):
    n_cells: int = Field(36, ge=8, le=160)
    dt_s: float = Field(60.0, ge=1, le=600)
    steady_dt_s: float = Field(90.0, ge=5, le=600)
    steady_max_steps: int = Field(1500, ge=50, le=20000)
    steady_tol_K_per_h: float = Field(1.0, ge=1e-3, le=50)
    steady_wall_capacity_factor: float = Field(0.02, ge=1e-4, le=1.0)
    gas_newton_tol: float = 1e-9
    balance_rel_tol: float = Field(1e-4, ge=1e-10, le=1e-1)


class Economics(_M):
    pellet_INR_t: float = 9500.0
    coal_INR_t: float = 7800.0
    dolomite_INR_t: float = 1800.0
    power_INR_kWh: float = 7.0
    dri_INR_t: float = 24500.0
    co2_factor_t_per_t_C: float = 3.664
    grid_emission_factor_t_per_MWh: float = 0.71
    provenance: Provenance = "PLACEHOLDER"


class Limits(_M):
    """Demo envelopes only.  Site alarm/trip limits are external and immutable."""
    max_bed_temperature_C: float = 1100.0
    max_gas_temperature_C: float = 1150.0
    max_shell_temperature_C: float = 380.0
    min_metallization_pct: float = 88.0
    max_exit_gas_temperature_C: float = 1250.0
    min_exit_gas_temperature_C: float = 800.0
    target_metallization_pct: float = 91.0
    provenance: Provenance = "PLACEHOLDER"


class PlantConfig(_M):
    meta: PlantMeta = PlantMeta()
    geometry: Geometry = Geometry()
    lining: Lining = Lining()
    pellet: PelletFeed = PelletFeed()
    coal: CoalStreams = CoalStreams()
    flux: FluxRecycle = FluxRecycle()
    air: AirSystem = AirSystem()
    offgas: OffGasTrain = OffGasTrain()
    cooler: Cooler = Cooler()
    separation: Separation = Separation()
    kinetics: Kinetics = Kinetics()
    heat: HeatTransfer = HeatTransfer()
    numerics: Numerics = Numerics()
    economics: Economics = Economics()
    limits: Limits = Limits()

    @model_validator(mode="after")
    def _check(self):
        g = self.geometry
        if not (g.rpm_min <= g.rpm <= g.rpm_max):
            raise ValueError("geometry.rpm must lie within [rpm_min, rpm_max]")
        lin = sum(layer.thickness_m for layer in self.lining.layers) + self.lining.shell_thickness_m
        if g.shell_diameter_m - 2 * (lin + g.accretion_thickness_m) < 0.6:
            raise ValueError("internal diameter < 0.6 m after lining/accretion")
        for t in self.air.secondary_tubes:
            if t.z_m > g.length_m:
                raise ValueError(f"air tube {t.tube_id} beyond kiln length")
        if self.coal.injection_throw_max_m <= self.coal.injection_throw_min_m:
            raise ValueError("injection throw max must exceed min")
        return self


def default_tubes(L: float, n: int, total_nm3h: float, first_frac=0.12, last_frac=0.86, w_first=0.7,
                  w_last=1.0) -> list[AirTube]:
    """Evenly spaced secondary-air tubes from 12 % to 86 % of kiln length with a
    mild increase of air toward the reduction zone (demo distribution)."""
    zs = [L * (first_frac + (last_frac - first_frac) * i / max(n - 1, 1)) for i in range(n)]
    w = [w_first + (w_last - w_first) * i / max(n - 1, 1) for i in range(n)]
    s = sum(w)
    return [AirTube(tube_id=f"SA{i+1:02d}", z_m=round(z, 2), flow_nm3h=round(total_nm3h * wi / s, 1),
                    max_nm3h=round(2.0 * total_nm3h * wi / s, 0)) for i, (z, wi) in enumerate(zip(zs, w))]


PRESETS = {
    # Illustrative capacity classes (NOT vendor data).  The 100 TPD case is the
    # tuned demo baseline; others scale feeds/air with throughput.
    "RK-50TPD": dict(L=36.0, D=2.4, n_tubes=6, rpm=0.45, scale=0.5, dam=0.35, cells=32, air=0.55),
    "RK-100TPD": dict(L=42.0, D=3.0, n_tubes=7, rpm=0.42, scale=1.0, dam=0.45, cells=36, air=1.0),
    "RK-350TPD": dict(L=72.0, D=4.8, n_tubes=10, rpm=0.40, scale=3.5, dam=0.70, cells=44, air=0.83, pel=1.40),
    "RK-500TPD": dict(L=80.0, D=5.0, n_tubes=11, rpm=0.40, scale=5.0, dam=0.75, cells=48, air=0.79, pel=1.38),
}
BASE_100 = dict(pellet=6.8, coal_f=3.9, coal_i=1.5, dol=0.20, prim=400.0, carrier=500.0, sec=15500.0,
                leak_f=400.0, leak_d=300.0, cooler_UA=14.0, water=90.0)


def preset_config(name: str = "RK-100TPD") -> PlantConfig:
    if name not in PRESETS:
        raise KeyError(f"unknown preset {name}; choose {list(PRESETS)}")
    p = PRESETS[name]
    k = p["scale"]
    b = BASE_100
    cfg = PlantConfig()
    cfg.meta.preset = name
    cfg.meta.name = f"Industry-X {name} rotary kiln (synthetic demo)"
    cfg.geometry.length_m, cfg.geometry.shell_diameter_m = p["L"], p["D"]
    cfg.geometry.rpm = p["rpm"]
    cfg.geometry.discharge_dam_height_m = p["dam"]
    cfg.pellet.feed_tph = round(b["pellet"] * k * p.get("pel", 1.0), 2)
    cfg.coal.feed_coal_tph, cfg.coal.injection_coal_tph = round(b["coal_f"] * k, 2), round(b["coal_i"] * k, 2)
    cfg.coal.injection_throw_max_m = round(0.38 * p["L"], 1)
    cfg.coal.injection_throw_min_m = round(0.071 * p["L"], 1)
    cfg.flux.dolomite_tph = round(b["dol"] * k, 2)
    cfg.air.primary_air_nm3h, cfg.air.injection_carrier_air_nm3h = round(b["prim"] * k), round(b["carrier"] * k)
    cfg.air.secondary_tubes = default_tubes(p["L"], p["n_tubes"], b["sec"] * k * p.get("air", 1.0))
    cfg.air.leak_feed_end_nm3h = round(b["leak_f"] * k ** 0.6)
    cfg.air.leak_discharge_end_nm3h = round(b["leak_d"] * k ** 0.6)
    cfg.numerics.n_cells = p["cells"]
    if p["cells"] >= 44:
        cfg.numerics.steady_max_steps = 3000
        cfg.numerics.steady_tol_K_per_h = 1.5  # large-kiln slow wall-node limit cycle (documented)
    cfg.cooler.UA_kW_K = round(b["cooler_UA"] * k, 1)
    cfg.cooler.water_flow_m3h = round(b["water"] * k, 0)
    cfg.cooler.diameter_m = round(2.2 * k ** 0.35, 2)
    cfg.cooler.length_m = round(30 * k ** 0.3, 1)
    return PlantConfig.model_validate(cfg.model_dump())
