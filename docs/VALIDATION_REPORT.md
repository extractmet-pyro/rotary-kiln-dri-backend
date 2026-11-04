# VALIDATION_REPORT (generated)

Generated 2026-11-03 13:51 UTC on Python 3.13.18 / Linux.
Release label: **SIMULATOR (synthetic demo)**. All results below are from SYNTHETIC configurations; they verify the software, not plant accuracy. Gate G11 (industrial acceptance) is SITE-PENDING.

## 1. Automated tests

Command `python -m pytest -q` - exit code 0, wall time 62 s.

| tests | failures | errors | skipped |
|---|---|---|---|
| 76 | 0 | 0 | 0 |

| test | time s | result |
|---|---|---|
| tests.e2e.test_walkthrough::test_walkthrough | 14.1 | pass |
| tests.integration.test_api::test_health_meta | 0.0 | pass |
| tests.integration.test_api::test_security_headers | 0.0 | pass |
| tests.integration.test_api::test_presets_and_config | 0.0 | pass |
| tests.integration.test_api::test_rbac_config_write_denied_for_anonymous | 0.0 | pass |
| tests.integration.test_api::test_cached_baseline_simulation_and_exports | 0.9 | pass |
| tests.integration.test_api::test_supervisory_mode_rejected | 0.0 | pass |
| tests.integration.test_api::test_mpc_recommend_and_decision | 3.1 | pass |
| tests.integration.test_api::test_data_endpoints | 0.5 | pass |
| tests.integration.test_api::test_admin_supervisory_cannot_enable | 0.0 | pass |
| tests.integration.test_api::test_adapters_are_read_only | 0.0 | pass |
| tests.integration.test_api::test_websocket_telemetry | 0.0 | pass |
| tests.ml.test_ml::test_synthetic_is_labelled_and_deterministic | 0.1 | pass |
| tests.ml.test_ml::test_no_leakage | 0.3 | pass |
| tests.ml.test_ml::test_training_pipeline_runs_and_reports | 1.1 | pass |
| tests.ml.test_ml::test_drift_tools | 0.0 | pass |
| tests.ml.test_ml::test_conservative_projection | 0.0 | pass |
| tests.mpc.test_mpc::test_recommendation_respects_bounds_and_ramps | 3.2 | pass |
| tests.mpc.test_mpc::test_locked_variable_unchanged | 1.5 | pass |
| tests.mpc.test_mpc::test_supervisory_mode_blocked | 3.2 | pass |
| tests.mpc.test_mpc::test_failed_optimiser_or_stale_data_not_actionable | 3.1 | pass |
| tests.mpc.test_mpc::test_out_of_domain_flagged | 0.0 | pass |
| tests.mpc.test_mpc::test_decision_requires_note_and_role | 0.0 | pass |
| tests.mpc.test_mpc::test_surrogate_fidelity_reported | 0.0 | pass |
| tests.physics.test_kinetics::test_no_reduction_at_equilibrium_or_without_reductant | 0.0 | pass |
| tests.physics.test_kinetics::test_reduction_increases_with_reducing_potential_and_temperature | 0.0 | pass |
| tests.physics.test_kinetics::test_boudouard_zero_without_carbon_and_positive_with_co2 | 0.0 | pass |
| tests.physics.test_kinetics::test_arthur_ratio_increases_with_T | 0.0 | pass |
| tests.physics.test_solver::test_steady_converges_and_conserves | 8.9 | pass |
| tests.physics.test_solver::test_nonnegative_inventories | 0.0 | pass |
| tests.physics.test_solver::test_counter_current_boundary | 0.0 | pass |
| tests.physics.test_solver::test_plausible_kpis | 0.0 | pass |
| tests.physics.test_solver::test_transient_from_steady_stays_steady | 1.1 | pass |
| tests.physics.test_solver::test_grid_refinement | 19.0 | pass |
| tests.physics.test_solver::test_invalid_inputs_rejected | 0.0 | pass |
| tests.physics.test_species_reactions::test_every_reaction_atom_balanced | 0.0 | pass |
| tests.physics.test_species_reactions::test_reaction_heats_have_expected_signs | 0.0 | pass |
| tests.physics.test_species_reactions::test_coal_basis_consistency_errors | 0.0 | pass |
| tests.physics.test_species_reactions::test_gcv_to_ncv | 0.0 | pass |
| tests.physics.test_species_reactions::test_vm_yield_element_closure | 0.0 | pass |
| tests.physics.test_species_reactions::test_pellet_assay_closure_and_rejection | 0.0 | pass |
| tests.physics.test_species_reactions::test_theoretical_oxygen_removal_hematite | 0.0 | pass |
| tests.physics.test_species_reactions::test_metallization_hand_calculation | 0.0 | pass |
| tests.physics.test_species_reactions::test_species_index_complete | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[Al2O3] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[C] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[CH4] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[CO] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[CO2] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[CaCO3] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[CaO] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[Fe] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[Fe2O3] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[Fe3O4] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[FeO] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[H2] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[H2O] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[H2S] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[MgCO3] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[MgO] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[N2] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[O2] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[SO2] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[SiO2] | 0.0 | pass |
| tests.physics.test_thermo::test_cp298_against_nist[TiO2] | 0.0 | pass |
| tests.physics.test_thermo::test_enthalpy_dimension_and_continuity | 0.0 | pass |
| tests.physics.test_thermo::test_fastK_equals_general | 0.0 | pass |
| tests.physics.test_thermo::test_boudouard_crossover_near_700C | 0.0 | pass |
| tests.physics.test_thermo::test_logK_fits_consistent_with_thermo_db[1000.0] | 0.0 | pass |
| tests.physics.test_thermo::test_logK_fits_consistent_with_thermo_db[1173.0] | 0.0 | pass |
| tests.physics.test_thermo::test_logK_fits_consistent_with_thermo_db[1273.0] | 0.0 | pass |
| tests.unit.test_units::test_temperature_roundtrip | 0.0 | pass |
| tests.unit.test_units::test_normal_volume_kmol | 0.0 | pass |
| tests.unit.test_units::test_actual_vs_normal_volume_differ | 0.0 | pass |
| tests.unit.test_units::test_dry_wet | 0.0 | pass |
| tests.unit.test_units::test_tph | 0.0 | pass |

## 2. Steady baselines (detailed physics)

| preset | solver | steps | metallization % | DRI t/d | coal kg/t | peak bed C | exit gas C | mass rel. res. | energy rel. res. | max element rel. res. | ledger res. % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| RK-50TPD | converged | 760 | 93.55 | 59 | 1102 | 1145 | 850 | 1.6e-07 | 1.5e-11 | 7.7e-15 | 0.365 |
| RK-100TPD | converged | 800 | 92.52 | 118 | 1095 | 1078 | 1214 | 3.2e-07 | 1.1e-11 | 9.2e-15 | 0.113 |
| RK-350TPD | converged | 600 | 92.50 | 576 | 788 | 1153 | 1057 | 1.1e-07 | 2.9e-11 | 5.7e-15 | 0.321 |
| RK-500TPD | converged | 620 | 93.46 | 808 | 802 | 1169 | 1034 | 6.0e-08 | 2.4e-11 | 2.5e-14 | 0.215 |

Note: for the 350/500 TPD geometries the uncalibrated model produces output above the nominal class - calibration required.

## 3. Transient run

Status completed; 60 outputs; max per-step residuals: mass 4.4e-07, energy 2.4e-10, Fe 9.2e-14; wall time 8 s.

## 4. Surrogate fidelity (GP, 6-fold CV on physics DOE)

61 design points used.

| output | CV RMSE |
|---|---|
| metallization_pct | 5.051 |
| dri_t_h | 0.042 |
| peak_bed_T_C | 28.598 |
| exit_gas_T_C | 33.906 |
| char_C_discharge_t_h | 0.032 |
| peak_shell_T_C | 3.219 |
| exit_O2_vol_pct_dry | 0.558 |
| accretion_risk_max | 0.058 |
| FeO_pct | 2.399 |
| C_pct | 0.006 |
| steam_t_h | 0.318 |

## 5. ML (SYNTHETIC data, chronological holdout)

| estimator | test MAE pp | RMSE | PI90 coverage |
|---|---|---|---|
| physics_only | 1.60 | 2.19 | 0.94 |
| ridge_ml_only | 4.52 | 5.39 | 0.85 |
| pls_ml_only | 8.11 | 9.65 | 0.73 |
| hgb_ml_only | 2.71 | 3.27 | 1.00 |
| hybrid_physics_plus_ridge_residual | 2.17 | 2.60 | 0.85 |

ML-C IsolationForest (any injected fault): precision 0.56, recall 0.55, false alarms 20.3/day. UNVALIDATED RESEARCH SUPPORT - evaluated on injected synthetic faults only.

## 6. Closed-loop simulation (MPC vs fixed setpoints)

| metric | fixed | MPC |
|---|---|---|
| mean_metallization | 90.72 | 91.13 |
| min_metallization | 89.04 | 87.70 |
| time_below_min_h | 0.00 | 1.00 |
| mean_specific_coal | 1090.22 | 1124.12 |
| max_peak_bed_T_C | 1088.80 | 1092.43 |

Outcome: **no demonstrated improvement** in this disturbance test (acceptance row G4-03 = FAIL). Reported as is.

## 7. Frontend

Playwright smoke test (`rotary-kiln-dri-frontend/tests/e2e/smoke.mjs`): all 14 screens load against a live backend with 0 console errors (run 2026-11-03, headless Chromium with SwiftShader WebGL).

## 8. Not executed here

* Render cloud deployment smoke test (requires the customer's Render account) - run `scripts/smoke_api.py https://<host>`.
* Docker image build (no Docker daemon in the build environment) - CI builds it (`docker build -t rk-twin-api .`).
* Plant validation (G11) - SITE-PENDING.
