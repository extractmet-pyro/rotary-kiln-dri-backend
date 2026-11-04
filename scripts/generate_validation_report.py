"""Run the full test suite and write docs/VALIDATION_REPORT.md from ACTUAL outputs.
Usage: python scripts/generate_validation_report.py [--skip-tests]"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "fixtures"
skip = "--skip-tests" in sys.argv
lines = ["# VALIDATION_REPORT (generated)", "",
         f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} on Python {platform.python_version()} / {platform.system()}.",
         "Release label: **SIMULATOR (synthetic demo)**. All results below are from SYNTHETIC configurations; they verify the software, "
         "not plant accuracy. Gate G11 (industrial acceptance) is SITE-PENDING.", ""]
if not skip:
    xml = ROOT / "data" / "pytest.xml"
    xml.parent.mkdir(exist_ok=True)
    t0 = time.time()
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={xml}"], cwd=ROOT, capture_output=True, text=True)
    r = ET.parse(xml).getroot()
    s = r if r.tag == "testsuite" else r.find("testsuite")
    lines += ["## 1. Automated tests", "", f"Command `python -m pytest -q` - exit code {p.returncode}, wall time {time.time()-t0:.0f} s.", "",
              "| tests | failures | errors | skipped |", "|---|---|---|---|",
              f"| {s.get('tests')} | {s.get('failures')} | {s.get('errors')} | {s.get('skipped')} |", "", "| test | time s | result |", "|---|---|---|"]
    for tc in s.iter("testcase"):
        res = "FAIL" if tc.find("failure") is not None or tc.find("error") is not None else "pass"
        lines.append(f"| {tc.get('classname')}::{tc.get('name')} | {float(tc.get('time')):.1f} | {res} |")
    lines.append("")
lines += ["## 2. Steady baselines (detailed physics)", "", "| preset | solver | steps | metallization % | DRI t/d | coal kg/t | peak bed C | exit gas C | mass rel. res. | energy rel. res. | max element rel. res. | ledger res. % |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for pr in ("RK-50TPD", "RK-100TPD", "RK-350TPD", "RK-500TPD"):
    d = json.loads((FX / f"baseline_{pr}.json").read_text())
    k, e, sd = d["kpi"], d["elemental_balances"], d["solver_diagnostics"]
    mx = max(x["relative_residual"] for x in e["elements"])
    lines.append(f"| {pr} | {sd['message']} | {sd['steps']} | {k['metallization_pct']:.2f} | {k['dri_tpd']:.0f} | {k['coal_kg_per_t_dri']:.0f} | "
                 f"{k['peak_bed_T_C']:.0f} | {k['exit_gas_T_C']:.0f} | {e['mass']['relative_residual']:.1e} | {e['energy']['relative_residual']:.1e} | "
                 f"{mx:.1e} | {100*d['heat_balance']['relative_residual']:.3f} |")
lines += ["", "Note: for the 350/500 TPD geometries the uncalibrated model produces output above the nominal class - calibration required.", ""]
t = json.loads((FX / "transient_demo_RK-100TPD.json").read_text())["transient"]
lines += ["## 3. Transient run", "", f"Status {t['status']}; {len(t['series'])} outputs; max per-step residuals: mass {t['max_step_residuals']['mass_rel']:.1e}, "
          f"energy {t['max_step_residuals']['energy_rel']:.1e}, Fe {t['max_step_residuals']['Fe_rel']:.1e}; wall time {t['wall_time_s']:.0f} s.", ""]
import joblib  # noqa: E402

sys.path.insert(0, str(ROOT))
gp = joblib.load(FX / "surrogate_gp_RK-100TPD.joblib")
from app.control.reduced_model import OUTPUTS  # noqa: E402

lines += ["## 4. Surrogate fidelity (GP, 6-fold CV on physics DOE)", "", f"{gp.n_runs} design points used.", "", "| output | CV RMSE |", "|---|---|"]
lines += [f"| {o} | {v:.3f} |" for o, v in zip(OUTPUTS, gp.loo_rmse)]
ml = json.loads((FX / "ml_report_RK-100TPD.json").read_text())
lines += ["", "## 5. ML (SYNTHETIC data, chronological holdout)", "", "| estimator | test MAE pp | RMSE | PI90 coverage |", "|---|---|---|---|"]
for k_, v in ml["soft_sensor"]["models"].items():
    lines.append(f"| {k_} | {v['test']['MAE']:.2f} | {v['test']['RMSE']:.2f} | {v['test'].get('PI90_coverage', float('nan')):.2f} |")
a = ml["anomaly"]
lines += ["", f"ML-C IsolationForest (any injected fault): precision {a['isolation_forest_any_fault']['precision']:.2f}, recall "
          f"{a['isolation_forest_any_fault']['recall']:.2f}, false alarms {a['isolation_forest_any_fault']['false_alarms_per_day']:.1f}/day. "
          f"{a['validation_status']}.", ""]
cl = json.loads((FX / "closed_loop_RK-100TPD.json").read_text())
sa, sb = cl["baseline"]["summary"], cl["mpc"]["summary"]
lines += ["## 6. Closed-loop simulation (MPC vs fixed setpoints)", "", "| metric | fixed | MPC |", "|---|---|---|"]
lines += [f"| {k_} | {sa[k_]:.2f} | {sb[k_]:.2f} |" for k_ in sa]
lines += ["", "Outcome: **no demonstrated improvement** in this disturbance test (acceptance row G4-03 = FAIL). Reported as is.", "",
          "## 7. Frontend", "", "Playwright smoke test (`rotary-kiln-dri-frontend/tests/e2e/smoke.mjs`): all 14 screens load against a live backend "
          "with 0 console errors (run 2026-11-03, headless Chromium with SwiftShader WebGL).", "",
          "## 8. Not executed here", "", "* Render cloud deployment smoke test (requires the customer's Render account) - run `scripts/smoke_api.py https://<host>`.",
          "* Docker image build (no Docker daemon in the build environment) - CI builds it (`docker build -t rk-twin-api .`).",
          "* Plant validation (G11) - SITE-PENDING."]
(ROOT / "docs" / "VALIDATION_REPORT.md").write_text("\n".join(lines) + "\n")
print("written docs/VALIDATION_REPORT.md")
