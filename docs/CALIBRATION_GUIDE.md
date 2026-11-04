# CALIBRATION_GUIDE - plant parameter identification

1. **Data**: >= 4 weeks of time-synchronised DCS/historian (1 min), lab (metallization, Fe(T), Fe(M), C, S), assays per lot
   (pellet, coal proximate+ultimate+NCV, ash fusion), weigh-feeder calibrations, shell-scanner maps, gas analyser data with
   sample-conditioning delay, inspection/ring records. Agree mass and heat balance boundaries.
2. **Reconcile** steady periods (`app/estimation/reconciliation.py`): Fe balance first, then C/ash balance; reject periods
   failing the chi-square gross-error test - never force closure.
3. **Static calibration** on detailed physics (bounded): order - (a) heat-transfer multipliers and shell-loss multiplier vs
   shell scanner + TC profile; (b) freeboard mixing efficiency vs exit gas T/O2; (c) gasification multiplier vs char at
   discharge and exit CO; (d) reduction multiplier vs lab metallization (RTD-aligned cohorts). Keep each within the bounds in
   `PlantConfig` and record identifiability (condition number in `calibration.py`).
4. **Dynamic**: step tests (feed coal, air, rpm) during approved windows -> `scripts/identify_dynamics.py` style FOPDT fits.
5. **Surrogate**: rerun `scripts/build_surrogate.py` around the calibrated point; accept only if CV RMSE meets the
   contractually agreed thresholds.
6. **Provenance**: every calibration stores data period, data hash, objective, algorithm, residuals, author and approval
   (PENDING until a process engineer approves). Roll back via config versions and the model registry.
7. **Blind test** on a frozen holdout campaign; report metallization error in percentage points, exit-T error, gas error,
   output-rate error and interval coverage.
