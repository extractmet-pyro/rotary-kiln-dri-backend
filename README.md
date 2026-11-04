# RK-DRI Twin - backend (Extractmet Private Limited)

Industrial digital twin, process simulator and **advisory** supervisory-control system for coal-based rotary-kiln DRI
production from iron-ore pellets. Release label: **SIMULATOR (synthetic demo)** - `model_not_validated` until site acceptance.

* First-principles quasi-1D counter-current finite-volume model: 23 balanced reactions, three-interface pellet kinetics,
  Boudouard/steam gasification, devolatilisation, calcination, sulfur, Kramers bed transport, gas/bed/wall/shell energy with
  radial refractory conduction and shell convection/radiation; steady + transient solvers with per-step mass/element/energy audit.
* Downstream cooler, magnetic separation, DSC/ABC/WHRB/ESP/stack; LHV energy ledger; DRI chemistry; emissions.
* GP surrogate + identified dynamics -> EKF observer and receding-horizon MPC with safety gates (no actuator write path).
* ML-A soft sensor, ML-B bounded residual correction (conservative projection), ML-C anomaly/accretion diagnostics.
* FastAPI v1 (OpenAPI at `/docs`), WebSocket telemetry, RBAC, audit, SQLite/Postgres + Alembic, Docker, Render blueprint.

Quick start:
```bash
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --port 8000
bash scripts/run_all_tests.sh
```
Deployment, security architecture and operations: [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md) (also `.docx`).
Science: [MODEL_EQUATIONS](docs/MODEL_EQUATIONS.md) · [MODEL_ASSUMPTIONS](docs/MODEL_ASSUMPTIONS.md) ·
[CALIBRATION_GUIDE](docs/CALIBRATION_GUIDE.md) · [MPC_SPECIFICATION](docs/MPC_SPECIFICATION.md) · [SAFETY_CASE](docs/SAFETY_CASE.md) ·
[VALIDATION_REPORT](docs/VALIDATION_REPORT.md) · [ACCEPTANCE_MATRIX](docs/ACCEPTANCE_MATRIX.csv) · [DATA_DICTIONARY](docs/DATA_DICTIONARY.csv) ·
[FILE_TREE](docs/FILE_TREE.md) · [DEMO_WALKTHROUGH](docs/DEMO_WALKTHROUGH.md).

Regenerate scientific fixtures: `python -m scripts.build_surrogate`, `python -m scripts.fit_gp_surrogate`,
`python -m scripts.identify_dynamics`, `python -m scripts.generate_fixtures`.

Proprietary - © 2026 Extractmet Private Limited. Plant identities anonymised as "Industry-X". Demo data are synthetic.
