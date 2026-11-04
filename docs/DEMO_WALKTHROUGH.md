# End-to-end demo walkthrough (10 minutes)
1. Open the frontend; header shows SYNTHETIC, SAFE_ADVISORY_ONLY, model_not_validated, API ready.
2. **Plant overview**: 12 KPIs (click for provenance), mini 3D kiln, temperatures, gas, alerts, live telemetry.
3. **Process big picture**: complete flowsheet with live numbers; switch preset RK-50/100/350/500 TPD in the header.
4. **3D kiln twin**: orbit/zoom, toggle cutaway, bed colour by reduction stage/temperature, axial slice, hover to inspect,
   click an air tube.
5. **Simulator**: change pellet moisture to 3.5 %, Run steady (fast numerics) -> compare with baseline -> export XLSX/PDF.
6. **Metallurgy & balances**: Sankey energy ledger, element residuals (~1e-15), DRI chemistry, reaction extents.
7. **Thermal & refractory**: radial lining field, heat-flux paths, shell loss.
8. **Live trends**: synthetic history with quality flags; dynamic demo (+6 % coal at 1 h, -4 % air at 5 h).
9. **Scenarios**: tornado, Pareto front, physics compare of templates.
10. **ML studio**: physics vs ML vs hybrid on chronological holdout; EKF parameter tracking vs synthetic truth.
11. **MPC centre**: compute recommendation, inspect gates and trajectories, sign in as `demo_operator`, approve/reject with a
    note (no actuator write), review closed-loop simulation.
12. **Diagnostics**, **Configuration & data** (validate config, preview a CSV), **Reports** (shift PDF, audit), **Admin**.
API-level equivalent: `tests/e2e/test_walkthrough.py`.
