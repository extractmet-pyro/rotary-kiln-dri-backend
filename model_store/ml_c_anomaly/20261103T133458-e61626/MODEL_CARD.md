# Model card - ml_c_anomaly (20261103T133458-e61626)

* Purpose: ML-C anomaly / accretion-precursor detection
* Status: UNVALIDATED RESEARCH SUPPORT
* Training data: SYNTHETIC history
* Split: chronological
* Features: 0 (see feature contract)
* Seed: 20261102
* Metrics (test, chronological holdout): {"isolation_forest_any_fault": {"precision": 0.5596899224806201, "recall": 0.546969696969697, "false_alarms_per_day": 20.285714285714285}, "rule_freeze_detector": {"precision": 1.0, "recall": 0.6944444444444444, "false_alarms_per_day": 0.0}}
* Limitations: synthetic benchmark does not demonstrate real-world performance; retrain and
  validate on site data (blocked/out-of-time) before any advisory use.
