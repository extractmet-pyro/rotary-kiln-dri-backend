# MODEL_ASSUMPTIONS, limitations and parameter lineage

Status: **SIMULATOR (synthetic demo)**. All plant numbers are FICTIONAL demonstration values for anonymised "Industry-X".

| Area | Assumption / simplification | Provenance | Action at site |
|---|---|---|---|
| Wustite | stoichiometric FeO in balances; non-stoichiometry ignored | DESIGN | acceptable; check FeO assays |
| Fe-O equilibria | log K fits (Bogdandy & Engell type), VERIFY-SOURCE | literature (verify) | confirm coefficients |
| Cp/Hf/S data | Maier-Kelley + NIST-JANAF values entered by developer; Cp(298) within 6 % of NIST (tested) | literature (verify) | verify against licensed tables |
| Pellet kinetics | three-interface shrinking core, isothermal pellet, single size class; k0/E are PLACEHOLDERS | PLACEHOLDER | calibrate on TGA/plant data |
| Char gasification | Langmuir-Hinshelwood Boudouard, A/E PLACEHOLDER, reactivity factor | PLACEHOLDER | CRI/char reactivity tests |
| Devolatilisation | single first-order (A = 5.7e4 /s, E = 100 kJ/mol), tar lumped into CH4 + soot | PLACEHOLDER | coal TGA |
| Bed gas | interstitial CO/CO2 pool in quasi-steady balance; small freeboard exchange (1e-3 m/s) | DESIGN | calibrate via exit gas |
| Freeboard combustion | mixing-limited (eta_mix per cell), WGS 50 % approach | PLACEHOLDER | calibrate on TC/gas profile |
| Heat transfer | Tscheng-Watkinson, penetration theory, gray gas; multipliers | literature + PLACEHOLDER | calibrate on shell scanner/TCs |
| Transport | Kramers-Croockewit; uniform material properties; no segregation of pellets/coal | literature | RTD tracer test |
| Sulfur | release with volatiles, empirical capture/pickup fractions; no NOx model | PLACEHOLDER | lab S balance |
| Dust | velocity-squared entrainment of char/ash fines | PLACEHOLDER | DSC/ESP catch weights |
| Accretion | risk proxy only - no wall-growth model | DESIGN | historical ring records |
| Off-gas/cooler | lumped steady models | DESIGN | site PFD data |
| Electrical | drive torque + empirical friction (mu_eff 0.06), fan laws | PLACEHOLDER | energy meters |
| Multiple steady states | kiln shows ignited/extinguished branches; initialisation from a staged profile | physics | operating procedure |
| Large kilns | uncalibrated model predicts output above nominal class for 350/500 TPD geometries (~1.6x) | finding | calibration required |
| Surrogate | GP global CV RMSE ~5 pp metallization; MPC gated on local sigma <= 3 pp | measured | retrain on site DOE |
| Closed loop | in the reported disturbance test MPC did NOT outperform fixed setpoints | measured | tuning + site dynamics |

Unmodelled: pellet swelling/breakage mechanics, DEM/CFD effects, multi-size pellets, liquid-phase formation, NOx,
detailed sulfur chemistry, burner flame structure, axial wall conduction, kiln ovality, accretion growth physics.
