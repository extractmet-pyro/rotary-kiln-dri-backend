# FILE_TREE - rotary-kiln-dri-backend

Per-file summary (generated from module docstrings/headers).

| path | purpose |
|---|---|
| `.dockerignore` | Docker build context exclusions |
| `.env.example` | Environment variables template (no secrets) |
| `.github/workflows/ci.yml` | GitHub Actions CI (lint, tests, build) |
| `.gitignore` | Git ignore rules |
| `Dockerfile` | Container image (python:3.13-slim, uvicorn) |
| `README.md` | Repository overview and quick start |
| `alembic/env.py` | Alembic environment: uses DATABASE_URL from app settings |
| `alembic/script.py.mako` | MAKO file |
| `alembic/versions/0001_initial.py` | initial schema v1: runs, recommendations, decisions, audit, plant_configs, materials, alerts |
| `alembic.ini` | Alembic migration config |
| `app/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/api/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/api/v1/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/api/v1/_shared.py` | Shared lazy resources for API routes (read-only fixtures, synthetic history) |
| `app/api/v1/admin.py` | Administration: RBAC overview, secrets STATUS (never values), retention, |
| `app/api/v1/alerts.py` | Alerts/events, diagnostics, metrics and reports |
| `app/api/v1/auth.py` | Login, token issue and current-user endpoints (RBAC) |
| `app/api/v1/config.py` | Plant configuration (validated, versioned) and material assay lots |
| `app/api/v1/deps.py` | Shared API dependencies: principal extraction and permission checks |
| `app/api/v1/health.py` | Liveness/readiness and service meta (no secrets) |
| `app/api/v1/ml.py` | ML training (restricted), registry, last training report |
| `app/api/v1/mpc.py` | MPC advisory: recommend, list, audit, decide (no actuator writes), closed-loop sim |
| `app/api/v1/plant_data.py` | Tag metadata, history (with quality flags) and file ingestion preview |
| `app/api/v1/quality.py` | Hybrid quality prediction (physics + bounded ML-B) with physics fallback |
| `app/api/v1/simulation.py` | Simulation jobs: submit, poll, results, exports |
| `app/api/v1/states.py` | Reconciled current state estimate (EKF on synthetic/replayed data) with provenance |
| `app/control/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/control/advisory.py` | Advisory workflow: scenario ranking, recommendation records, operator |
| `app/control/constraints.py` | MPC variable definitions, bounds, ramp limits and soft-constraint policy |
| `app/control/dynamics.py` | Multi-rate dynamic response model (FOPDT step responses per MV/DV -> CV) |
| `app/control/mpc.py` | Receding-horizon constrained supervisory MPC (advisory only) |
| `app/control/optimizer.py` | Steady-state economic optimisation, Pareto fronts, verification of MPC end |
| `app/control/reduced_model.py` | Reduced-order surrogate of the steady physics model for MPC and estimation |
| `app/control/safety_gates.py` | Safety gates applied before any recommendation is shown as actionable |
| `app/core/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/core/exceptions.py` | Typed exceptions mapped to a consistent API error envelope |
| `app/core/logging.py` | Structured JSON logging (no feedstock/plant secrets in logs) |
| `app/core/security.py` | Authentication (HMAC-signed bearer tokens), server-enforced RBAC, rate limiting |
| `app/core/settings.py` | Runtime settings from environment variables (no secrets in code) |
| `app/core/units.py` | Unit manager. SI is used internally (kg, kmol, m, s, K, Pa, J) |
| `app/estimation/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/estimation/calibration.py` | Offline parameter identification with provenance |
| `app/estimation/observer.py` | State/parameter observer: constrained extended Kalman filter |
| `app/estimation/reconciliation.py` | Data reconciliation and gross-error detection |
| `app/estimation/uncertainty.py` | Uncertainty propagation and lab-sample cohort alignment |
| `app/integration/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/integration/base.py` | Uniform adapter interface: read_recent(), read_range(), subscribe(), health() |
| `app/integration/csv_excel.py` | CSV / XLSX importer with tag mapping, unit validation and UTC normalisation |
| `app/integration/historian.py` | Historian bulk/replay adapter: replays time-stamped logs with correct causal |
| `app/integration/mqtt_reader.py` | Optional MQTT subscriber for a site-approved broker (TLS + client certs) |
| `app/integration/opcua_reader.py` | Optional plant-approved OPC UA READ-ONLY reader (on-premises connector only) |
| `app/integration/rest.py` | Validated REST push/pull adapter (site gateway -> twin).  Pushed batches are |
| `app/integration/synthetic.py` | Deterministic SYNTHETIC plant-history generator (no-credential fallback) |
| `app/main.py` | FastAPI application: Rotary-Kiln DRI Digital Twin (simulation + advisory) |
| `app/ml/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/ml/drift.py` | Distribution-shift and out-of-distribution checks |
| `app/ml/explain.py` | Model explanations (associational, not causal) |
| `app/ml/features.py` | Causal feature engineering with an explicit feature data contract |
| `app/ml/predict.py` | Hybrid quality prediction with automatic physics-only fallback and a |
| `app/ml/registry.py` | Versioned model registry (joblib artifact + metadata + model card) |
| `app/ml/train.py` | Training pipelines for ML-A (quality soft sensor), ML-B (bounded physics |
| `app/ml/validate.py` | ML validation utilities: leakage checks and runtime input validation |
| `app/physics/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/physics/balances.py` | Conservation audits and the energy ledger |
| `app/physics/bed_transport.py` | Solids transport: bed geometry, Kramers-Croockewit/Saeman bed-depth profile, |
| `app/physics/cooler.py` | Downstream units at aggregate fidelity: rotary product cooler, magnetic |
| `app/physics/finite_volume.py` | Coupled quasi-1D finite-volume rotary-kiln model (counter-current) |
| `app/physics/heat_transfer.py` | Heat-transfer closures for the freeboard gas, bed, wall and shell |
| `app/physics/kinetics.py` | Rate laws: pellet reduction (three-interface unreacted-core model), char |
| `app/physics/postprocess.py` | Assemble traceable results (profiles, balances, quality, energy, emissions) |
| `app/physics/properties.py` | Gas and solid transport properties (engineering correlations) |
| `app/physics/reactions.py` | Independent reaction set, stoichiometric matrix and reaction enthalpies |
| `app/physics/species.py` | Auditable species list, atom matrices and feed-assay -> species conversion |
| `app/physics/steady_state.py` | Steady counter-current solution by pseudo-transient continuation |
| `app/physics/thermo.py` | Temperature-dependent thermochemistry (self-contained offline fallback) |
| `app/physics/transient.py` | Dynamic forward simulation with scheduled operating changes |
| `app/schemas/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/schemas/plant.py` | Schema-validated plant configuration (units in field names; plausibility guards) |
| `app/schemas/simulation.py` | API request/response models for simulations, MPC, ML and scenarios |
| `app/services/__init__.py` | Rotary-kiln DRI digital twin package |
| `app/services/audit.py` | Audit helpers (structured, append-only) |
| `app/services/compute.py` | Compute-heavy job bodies (executed in a separate worker process) |
| `app/services/jobs.py` | Persistence-backed background jobs |
| `app/services/metrics.py` | Service metrics (request counters, job statistics) |
| `app/services/reports.py` | Exports: JSON, CSV (profiles), XLSX (multi-sheet) and a server-side PDF |
| `app/services/scenario_manager.py` | Pre-defined what-if scenario templates (fictional; for demonstration) |
| `docs/ACCEPTANCE_MATRIX.csv` | Acceptance gates with PASS/FAIL/DEMO-ONLY/SITE-PENDING |
| `docs/CALIBRATION_GUIDE.md` | Site calibration procedure |
| `docs/DATA_DICTIONARY.csv` | Plant tag dictionary |
| `docs/DEMO_WALKTHROUGH.md` | End-to-end demo script |
| `docs/DEPLOYMENT_GUIDE.docx` | Word version of the deployment guide |
| `docs/DEPLOYMENT_GUIDE.md` | Step-by-step GitHub + Render + on-prem deployment |
| `docs/FILE_TREE.md` | This file |
| `docs/MODEL_ASSUMPTIONS.md` | Assumptions and limits |
| `docs/MODEL_EQUATIONS.md` | All governing equations |
| `docs/MPC_SPECIFICATION.md` | MPC formulation, constraints, gates |
| `docs/RELEASE_NOTES.md` | Release notes |
| `docs/SAFETY_CASE.md` | Safety and cybersecurity case |
| `docs/VALIDATION_REPORT.md` | Generated from actual test outputs |
| `docs/architecture.mmd` | Architecture diagram source (Mermaid) |
| `docs/architecture.png` | Rendered architecture diagram |
| `docs/commercial/Extractmet_RK-DRI_Twin_Pitch_Deck.pptx` | PPTX file |
| `docs/commercial/Extractmet_RK-DRI_Twin_Product_Brief.docx` | DOCX file |
| `docs/openapi.json` | Exported OpenAPI schema |
| `examples/README.md` | Repository overview and quick start |
| `examples/mpc_request.json` | JSON file |
| `examples/simulation_request_moisture.json` | JSON file |
| `fixtures/baseline_RK-100TPD.json` | Precomputed fixture (synthetic demo) |
| `fixtures/baseline_RK-350TPD.json` | Precomputed fixture (synthetic demo) |
| `fixtures/baseline_RK-500TPD.json` | Precomputed fixture (synthetic demo) |
| `fixtures/baseline_RK-50TPD.json` | Precomputed fixture (synthetic demo) |
| `fixtures/closed_loop_RK-100TPD.json` | Precomputed fixture (synthetic demo) |
| `fixtures/doe_RK-100TPD.csv` | CSV file |
| `fixtures/dynamics_RK-100TPD.json` | Precomputed fixture (synthetic demo) |
| `fixtures/ml_report_RK-100TPD.json` | Precomputed fixture (synthetic demo) |
| `fixtures/surrogate_RK-100TPD.json` | Precomputed fixture (synthetic demo) |
| `fixtures/surrogate_gp_RK-100TPD.joblib` | Serialized model artifact |
| `fixtures/synthetic_history_RK-100TPD.csv.gz` | GZ file |
| `fixtures/transient_demo_RK-100TPD.json` | Precomputed fixture (synthetic demo) |
| `infra/docker-compose.onprem.yml` | YML file |
| `model_store/ml_a_soft_sensor/20261103T133458-a8fd19/MODEL_CARD.md` | MD file |
| `model_store/ml_a_soft_sensor/20261103T133458-a8fd19/meta.json` | JSON file |
| `model_store/ml_a_soft_sensor/20261103T133458-a8fd19/model.joblib` | Serialized model artifact |
| `model_store/ml_a_soft_sensor/ACTIVE` | file |
| `model_store/ml_b_residual_correction/20261103T133458-47e374/MODEL_CARD.md` | MD file |
| `model_store/ml_b_residual_correction/20261103T133458-47e374/meta.json` | JSON file |
| `model_store/ml_b_residual_correction/20261103T133458-47e374/model.joblib` | Serialized model artifact |
| `model_store/ml_b_residual_correction/ACTIVE` | file |
| `model_store/ml_c_anomaly/20261103T133458-e61626/MODEL_CARD.md` | MD file |
| `model_store/ml_c_anomaly/20261103T133458-e61626/meta.json` | JSON file |
| `model_store/ml_c_anomaly/20261103T133458-e61626/model.joblib` | Serialized model artifact |
| `model_store/ml_c_anomaly/ACTIVE` | file |
| `notebooks/README.md` | Repository overview and quick start |
| `pyproject.toml` | Project metadata, ruff config |
| `pytest.ini` | pytest configuration |
| `render.yaml` | Render blueprint |
| `requirements-dev.txt` | Test/lint dependencies |
| `requirements.lock` | Pinned runtime dependencies |
| `scripts/build_surrogate.py` | Generate the physics DOE and fit the MPC/observer surrogate |
| `scripts/fit_gp_surrogate.py` | Fit the GP surrogate from an existing physics DOE CSV (no new physics runs) |
| `scripts/generate_fixtures.py` | Regenerate all deterministic SYNTHETIC demo fixtures |
| `scripts/generate_validation_report.py` | Run the full test suite and write docs/VALIDATION_REPORT.md from ACTUAL outputs |
| `scripts/identify_dynamics.py` | Identify FOPDT time constants/dead times from step tests on the detailed |
| `scripts/make_zip.sh` | Shell script |
| `scripts/migrate.sh` | Shell script |
| `scripts/run_all_tests.sh` | Shell script |
| `scripts/run_local.sh` | Shell script |
| `scripts/smoke_api.py` | API smoke test against a running service.  Usage: python scripts/smoke_api.py https://<host> |
| `tests/__init__.py` | package marker |
| `tests/conftest.py` | Shared pytest fixtures (temp DB, test client, configs) |
| `tests/e2e/__init__.py` | package marker |
| `tests/e2e/test_walkthrough.py` | End-to-end demo walkthrough (API level): mirrors docs/DEMO_WALKTHROUGH.md |
| `tests/integration/__init__.py` | package marker |
| `tests/integration/test_api.py` | API integration tests across all routers |
| `tests/ml/__init__.py` | package marker |
| `tests/ml/test_ml.py` | ML training, leakage, conformal and drift tests |
| `tests/mpc/__init__.py` | package marker |
| `tests/mpc/test_mpc.py` | MPC constraints, safety gates and advisory tests |
| `tests/physics/__init__.py` | package marker |
| `tests/physics/test_kinetics.py` | Reduction/gasification kinetics tests |
| `tests/physics/test_solver.py` | Solver verification: conservation, positivity, boundary conditions, |
| `tests/physics/test_species_reactions.py` | Species, coal reconciliation and atom-balance tests |
| `tests/physics/test_thermo.py` | Thermodynamic data and equilibrium tests |
| `tests/unit/__init__.py` | package marker |
| `tests/unit/test_units.py` | Unit conversion tests |
