# MPC_SPECIFICATION - supervisory advisory MPC

* **MVs** (only if commandable at site): pellet feed, feed-end coal, injection coal, secondary-air scale (all tubes), rpm.
  Bounds +/-10-25 % of baseline (demo), ramp per interval 2-5 %, lockable. Non-commandable items are disturbances.
* **DVs**: char reactivity (gasification multiplier), pellet reduction multiplier, pellet moisture (EKF/lab).
* **CVs**: metallization at discharge (after transport delay), peak bed T, exit gas T, peak shell T, DRI t/h, char at
  discharge, accretion risk, steam.
* **Model**: gain-scheduled step response: y = y_ss(u0) + bias + sum K(u0) du S(t - t_m - theta; tau), K = Jacobian of
  the GP surrogate, (tau, theta) identified from physics step tests. DMC-style constant output bias from measurements.
* **Horizons**: interval 30 min, Np = 16 (8 h, covers solids transit), Nc = 4 (configurable).
* **Objective** (normalised): w_M ((M - M*)/2)^2 + w_T ((T_bed - (T_max - 25))/25)^2 + w_C coal/coal0 + w_E energy +
  w_CO2 + w_R risk - w_thr DRI/DRI0 + w_U sum (du/range)^2 + terminal nonlinear cost + uncertainty penalty (local GP sigma)
  + 1e3 * slack^2 for soft envelopes (met min, bed/shell/exit T, risk).
* **Hard constraints**: MV bounds, ramps, cumulative ranges (linear inequalities) - never relaxed. Site alarm/trip limits are
  external and immutable.
* **Solver**: SciPy SLSQP; timeout; failure -> no recommendation.
* **Sequence**: gates -> estimate -> predict -> optimise -> nonlinear end-point check -> uncertainty band -> safety gates ->
  ranked recommendation -> operator approve/reject/defer with mandatory note -> audit -> repeat.
* **Safety gates**: mode (SITE_SUPERVISORY disabled), optimiser success, predicted envelope, surrogate domain, local
  fidelity (sigma_met <= 3 pp), data freshness (shadow/advisory).
* **Evidence**: closed-loop simulation vs fixed setpoints with a char-reactivity disturbance is in
  `fixtures/closed_loop_RK-100TPD.json`; the MPC did not show a clear advantage in that test (reported as is).
