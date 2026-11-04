# Release notes
## 1.0.0 (2026-11-03) - SIMULATOR (synthetic demo)
* Quasi-1D counter-current FV physics (23 reactions, three-interface pellet kinetics, Kramers transport, radial wall), steady +
  transient solvers with per-step conservation audit (element closure ~1e-15, energy ~1e-11 relative).
* Four capacity presets (50/100/350/500 TPD class, illustrative), cooler, separation, ABC/WHRB/ESP train, energy ledger.
* GP surrogate (65-point DOE), identified FOPDT dynamics, EKF observer, reconciliation, calibration utilities.
* ML-A/B/C pipelines with chronological splits, conformal intervals, registry, drift/OOD guards.
* Advisory MPC (5 scenarios, ramps/bounds, safety gates, approve/reject audit), closed-loop simulation.
* FastAPI v1 + WebSocket telemetry, RBAC, rate limiting, SQLite/Postgres, Alembic, Docker, Render blueprints.
* Operator desk (Vite + Three.js + Plotly): 14 screens incl. 3D twin and process big picture.
Known limitations: see MODEL_ASSUMPTIONS.md. G11 (industrial acceptance) SITE-PENDING.
