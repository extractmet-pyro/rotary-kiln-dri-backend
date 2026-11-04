"""API request/response models for simulations, MPC, ML and scenarios."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["DEMO_SYNTHETIC", "OFFLINE_SIMULATION", "HISTORICAL_REPLAY", "SHADOW", "ADVISORY", "SITE_SUPERVISORY"]


class FeedInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pellet_feed_tph: float | None = Field(None, ge=0, le=150)
    feed_coal_tph: float | None = Field(None, ge=0, le=100)
    injected_coal_tph: float | None = Field(None, ge=0, le=60)
    dolomite_tph: float | None = Field(None, ge=0, le=10)
    recycle_char_tph: float | None = Field(None, ge=0, le=10)


class ScheduleEvent(BaseModel):
    t_min: float = Field(..., ge=0)
    changes: dict[str, float]


class SimSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["steady", "transient"] = "steady"
    duration_min: float = Field(240, ge=10, le=72 * 60)
    output_interval_min: float = Field(10, ge=1, le=240)
    schedule: list[ScheduleEvent] = []
    fast: bool = False


class SimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_name: str = Field("baseline", max_length=120)
    mode: Mode = "OFFLINE_SIMULATION"
    preset: str = "RK-100TPD"
    plant_config_version: str | None = None
    plant_config: dict | None = None
    feed: FeedInputs = FeedInputs()
    disturbances: dict[str, float] = {}
    overrides: dict[str, Any] = {}
    simulation: SimSpec = SimSpec()
    campaign_id: str = ""
    feed_batch_id: str = ""


class JobAccepted(BaseModel):
    run_id: str
    status: str
    cached: bool = False
    poll: str


class MPCRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str = "RK-100TPD"
    scenario: Literal["maximize_metallization", "minimize_specific_coal", "maximize_throughput",
                      "minimize_thermal_risk", "multiobjective"] = "multiobjective"
    current: dict[str, float] = {}
    measurements: dict[str, float] = {}
    locked: list[str] = []
    mode: Mode = "OFFLINE_SIMULATION"
    data_timestamp_utc: str | None = None
    rank_all: bool = True
    verify_with_physics: bool = False
    interval_min: float = Field(30, ge=5, le=240)
    horizon_steps: int = Field(16, ge=4, le=48)
    control_steps: int = Field(4, ge=1, le=8)
    weights: dict[str, float] = {}
    mv_overrides: dict[str, dict[str, float]] = {}


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject", "defer"]
    note: str = Field(..., min_length=5, max_length=2000)
    override_minutes: float = Field(0, ge=0, le=720)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenarios: list[SimulationRequest] = Field(..., min_length=1, max_length=6)


class SensitivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str = "RK-100TPD"
    method: Literal["surrogate", "physics"] = "surrogate"
    rel_step: float = Field(0.08, gt=0, le=0.3)
    outputs: list[str] = ["metallization_pct", "peak_bed_T_C", "char_C_discharge_t_h", "exit_gas_T_C"]


class QualityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str = "RK-100TPD"
    current: dict[str, float] = {}
    ml_enabled: bool = True


class TrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: float = Field(14, ge=3, le=60)
    seed: int = 42


class ClosedLoopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str = "RK-100TPD"
    hours: float = Field(10, ge=2, le=36)
    interval_min: float = Field(60, ge=15, le=180)
    disturbance_t_h: float = Field(1.0, ge=0)
    disturbance: dict[str, float] = {"kinetics.gasification_multiplier": 0.85}
    scenario: str = "multiobjective"
