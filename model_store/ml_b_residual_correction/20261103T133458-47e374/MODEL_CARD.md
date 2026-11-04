# Model card - ml_b_residual_correction (20261103T133458-47e374)

* Purpose: ML-B bounded residual correction of physics metallization (+/-3 pp)
* Status: DEMO - synthetic
* Training data: SYNTHETIC history
* Split: chronological 60/20/20
* Features: 26 (see feature contract)
* Seed: 20261102
* Metrics (test, chronological holdout): {"MAE": 2.166803600232022, "RMSE": 2.6019632505690087, "bias": -0.9927776282364155, "n": 33, "resid_lag1_autocorr": 0.48823480699083927, "PI90_coverage": 0.8484848484848485, "PI90_mean_width": 7.395215077885638}
* Limitations: synthetic benchmark does not demonstrate real-world performance; retrain and
  validate on site data (blocked/out-of-time) before any advisory use.
