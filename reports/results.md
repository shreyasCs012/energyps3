# EnergySense Twin — Phase 9 evaluation

> **SYNTHETIC DATA — simulation-based projections.** This campaign is not measured facility performance.

## Campaign design

- Scenarios: S1, S2, S3, S4
- Seeds per scenario: 20
- Optimizer ensemble seeds: 3
- Policy checkpoints: 08:00, 12:00, 16:00
- Runtime: 602.65 seconds
- P0: plant baseline; P1: threshold alert only; P2: naive idle shutdown; P3: EnergySense optimizer.

## Overall policy results

Positive paired delta means the policy value exceeds baseline; for energy/cost/emissions, negative is an improvement.

| Metric | Policy | Mean | 95% CI | Paired delta vs P0 (95% CI) |
|---|---|---:|---:|---:|
| energy_kwh | P0_baseline | 438.804 | [427.291, 450.317] | 0.000 [0.000, 0.000] |
| energy_kwh | P1_threshold_alert | 438.804 | [427.291, 450.317] | 0.000 [0.000, 0.000] |
| energy_kwh | P2_idle_shutdown | 435.446 | [424.172, 446.720] | -3.358 [-4.059, -2.657] |
| energy_kwh | P3_optimizer | 430.633 | [418.709, 442.558] | -8.171 [-10.330, -6.012] |
| peak_15min_kw | P0_baseline | 43.077 | [42.554, 43.601] | 0.000 [0.000, 0.000] |
| peak_15min_kw | P1_threshold_alert | 43.077 | [42.554, 43.601] | 0.000 [0.000, 0.000] |
| peak_15min_kw | P2_idle_shutdown | 43.140 | [42.664, 43.615] | 0.062 [-0.057, 0.182] |
| peak_15min_kw | P3_optimizer | 43.028 | [42.511, 43.545] | -0.049 [-0.112, 0.014] |
| cost_inr | P0_baseline | 4147.518 | [4042.272, 4252.764] | 0.000 [0.000, 0.000] |
| cost_inr | P1_threshold_alert | 4147.518 | [4042.272, 4252.764] | 0.000 [0.000, 0.000] |
| cost_inr | P2_idle_shutdown | 4121.110 | [4018.038, 4224.182] | -26.408 [-32.587, -20.230] |
| cost_inr | P3_optimizer | 4080.242 | [3972.392, 4188.093] | -67.276 [-84.838, -49.713] |
| co2_kg | P0_baseline | 311.551 | [303.377, 319.725] | 0.000 [0.000, 0.000] |
| co2_kg | P1_threshold_alert | 311.551 | [303.377, 319.725] | 0.000 [0.000, 0.000] |
| co2_kg | P2_idle_shutdown | 309.167 | [301.162, 317.171] | -2.384 [-2.882, -1.886] |
| co2_kg | P3_optimizer | 305.750 | [297.283, 314.216] | -5.801 [-7.334, -4.268] |
| idle_waste_kwh | P0_baseline | 21.734 | [18.206, 25.263] | 0.000 [0.000, 0.000] |
| idle_waste_kwh | P1_threshold_alert | 21.734 | [18.206, 25.263] | 0.000 [0.000, 0.000] |
| idle_waste_kwh | P2_idle_shutdown | 16.579 | [14.001, 19.158] | -5.155 [-6.237, -4.072] |
| idle_waste_kwh | P3_optimizer | 18.740 | [15.882, 21.597] | -2.994 [-4.334, -1.655] |
| restarts | P0_baseline | 5.000 | [4.951, 5.049] | 0.000 [0.000, 0.000] |
| restarts | P1_threshold_alert | 5.000 | [4.951, 5.049] | 0.000 [0.000, 0.000] |
| restarts | P2_idle_shutdown | 8.425 | [7.825, 9.025] | 3.425 [2.824, 4.026] |
| restarts | P3_optimizer | 5.312 | [5.166, 5.459] | 0.312 [0.175, 0.450] |
| late_jobs | P0_baseline | 3.975 | [3.941, 4.009] | 0.000 [0.000, 0.000] |
| late_jobs | P1_threshold_alert | 3.975 | [3.941, 4.009] | 0.000 [0.000, 0.000] |
| late_jobs | P2_idle_shutdown | 4.375 | [4.230, 4.520] | 0.400 [0.262, 0.538] |
| late_jobs | P3_optimizer | 3.875 | [3.780, 3.970] | -0.100 [-0.190, -0.010] |
| comfort_violation_min | P0_baseline | 586.263 | [561.538, 610.987] | 0.000 [0.000, 0.000] |
| comfort_violation_min | P1_threshold_alert | 586.263 | [561.538, 610.987] | 0.000 [0.000, 0.000] |
| comfort_violation_min | P2_idle_shutdown | 586.263 | [561.538, 610.987] | 0.000 [0.000, 0.000] |
| comfort_violation_min | P3_optimizer | 582.900 | [557.606, 608.194] | -3.362 [-5.113, -1.612] |
| constraint_violations | P0_baseline | 7.638 | [7.047, 8.228] | 0.000 [0.000, 0.000] |
| constraint_violations | P1_threshold_alert | 7.638 | [7.047, 8.228] | 0.000 [0.000, 0.000] |
| constraint_violations | P2_idle_shutdown | 9.213 | [8.084, 10.341] | 1.575 [0.591, 2.559] |
| constraint_violations | P3_optimizer | 8.162 | [7.427, 8.898] | 0.525 [0.066, 0.984] |
| command_failures | P0_baseline | 0.000 | [0.000, 0.000] | 0.000 [0.000, 0.000] |
| command_failures | P1_threshold_alert | 0.000 | [0.000, 0.000] | 0.000 [0.000, 0.000] |
| command_failures | P2_idle_shutdown | 0.037 | [-0.004, 0.079] | 0.037 [-0.004, 0.079] |
| command_failures | P3_optimizer | 0.013 | [-0.012, 0.037] | 0.013 [-0.012, 0.037] |

## Optimizer predicted vs plant realized

- **energy_kwh:** projected 8.562; realized 8.171; projection error 0.391.
- **cost_inr:** projected 105.369; realized 67.276; projection error 38.093.
- **co2_kg:** projected 6.079; realized 5.801; projection error 0.277.
- **peak_15min_kw:** projected 3.040; realized 0.049; projection error 2.991.
- **late_jobs:** projected 0.133; realized 0.100; projection error 0.033.

## Forecast, anomaly, and root-cause evaluation

### S1

- Horizon 4: hist_gradient_boosting MAE 3.110, RMSE 5.328.
- Horizon 4: moving_average MAE 5.564, RMSE 9.689.
- Horizon 4: naive_yesterday MAE 5.427, RMSE 8.011.
- Horizon 4: seasonal_naive MAE 5.136, RMSE 8.059.
- Horizon 8: hist_gradient_boosting MAE 5.570, RMSE 8.238.
- Horizon 8: moving_average MAE 9.551, RMSE 14.247.
- Horizon 8: naive_yesterday MAE 5.504, RMSE 8.067.
- Horizon 8: seasonal_naive MAE 5.208, RMSE 8.116.
- Horizon 16: hist_gradient_boosting MAE 9.681, RMSE 12.378.
- Horizon 16: moving_average MAE 14.636, RMSE 18.767.
- Horizon 16: naive_yesterday MAE 5.663, RMSE 8.183.
- Horizon 16: seasonal_naive MAE 5.359, RMSE 8.232.
- Horizon 24: hist_gradient_boosting MAE 12.622, RMSE 15.207.
- Horizon 24: moving_average MAE 18.511, RMSE 21.904.
- Horizon 24: naive_yesterday MAE 5.832, RMSE 8.305.
- Horizon 24: seasonal_naive MAE 5.519, RMSE 8.354.
- Threshold anomaly baseline: precision 0.000, recall 0.000, F1 0.000.

### S2

- Horizon 4: hist_gradient_boosting MAE 3.179, RMSE 5.387.
- Horizon 4: moving_average MAE 5.523, RMSE 9.051.
- Horizon 4: naive_yesterday MAE 4.850, RMSE 7.277.
- Horizon 4: seasonal_naive MAE 4.541, RMSE 6.928.
- Horizon 8: hist_gradient_boosting MAE 5.632, RMSE 8.293.
- Horizon 8: moving_average MAE 9.096, RMSE 13.483.
- Horizon 8: naive_yesterday MAE 4.918, RMSE 7.328.
- Horizon 8: seasonal_naive MAE 4.605, RMSE 6.976.
- Horizon 16: hist_gradient_boosting MAE 9.679, RMSE 12.913.
- Horizon 16: moving_average MAE 13.835, RMSE 17.887.
- Horizon 16: naive_yesterday MAE 5.061, RMSE 7.433.
- Horizon 16: seasonal_naive MAE 4.739, RMSE 7.077.
- Horizon 24: hist_gradient_boosting MAE 13.097, RMSE 15.999.
- Horizon 24: moving_average MAE 17.700, RMSE 20.703.
- Horizon 24: naive_yesterday MAE 5.212, RMSE 7.544.
- Horizon 24: seasonal_naive MAE 4.880, RMSE 7.181.
- Threshold anomaly baseline: precision 0.000, recall 0.000, F1 0.000.

### S3

- Horizon 4: hist_gradient_boosting MAE 3.145, RMSE 4.957.
- Horizon 4: moving_average MAE 5.598, RMSE 9.146.
- Horizon 4: naive_yesterday MAE 4.309, RMSE 6.943.
- Horizon 4: seasonal_naive MAE 5.424, RMSE 8.333.
- Horizon 8: hist_gradient_boosting MAE 5.663, RMSE 7.823.
- Horizon 8: moving_average MAE 9.420, RMSE 13.942.
- Horizon 8: naive_yesterday MAE 4.370, RMSE 6.992.
- Horizon 8: seasonal_naive MAE 5.500, RMSE 8.392.
- Horizon 16: hist_gradient_boosting MAE 9.416, RMSE 12.274.
- Horizon 16: moving_average MAE 14.510, RMSE 19.047.
- Horizon 16: naive_yesterday MAE 4.496, RMSE 7.093.
- Horizon 16: seasonal_naive MAE 5.660, RMSE 8.513.
- Horizon 24: hist_gradient_boosting MAE 13.130, RMSE 15.358.
- Horizon 24: moving_average MAE 19.521, RMSE 22.698.
- Horizon 24: naive_yesterday MAE 4.630, RMSE 7.198.
- Horizon 24: seasonal_naive MAE 5.829, RMSE 8.639.
- Threshold anomaly baseline: precision 0.000, recall 0.000, F1 0.000.

### S4

- Horizon 4: hist_gradient_boosting MAE 2.335, RMSE 4.182.
- Horizon 4: moving_average MAE 4.718, RMSE 8.671.
- Horizon 4: naive_yesterday MAE 3.404, RMSE 7.104.
- Horizon 4: seasonal_naive MAE 2.783, RMSE 5.159.
- Horizon 8: hist_gradient_boosting MAE 4.075, RMSE 6.820.
- Horizon 8: moving_average MAE 8.199, RMSE 12.609.
- Horizon 8: naive_yesterday MAE 3.452, RMSE 7.154.
- Horizon 8: seasonal_naive MAE 2.822, RMSE 5.195.
- Horizon 16: hist_gradient_boosting MAE 7.244, RMSE 10.514.
- Horizon 16: moving_average MAE 14.689, RMSE 18.584.
- Horizon 16: naive_yesterday MAE 3.552, RMSE 7.257.
- Horizon 16: seasonal_naive MAE 2.904, RMSE 5.270.
- Horizon 24: hist_gradient_boosting MAE 10.729, RMSE 13.843.
- Horizon 24: moving_average MAE 20.501, RMSE 23.459.
- Horizon 24: naive_yesterday MAE 3.658, RMSE 7.365.
- Horizon 24: seasonal_naive MAE 2.991, RMSE 5.348.
- Threshold anomaly baseline: precision 0.000, recall 0.000, F1 0.000.

## CV state evaluation

- Simulated CV accuracy: 0.919 across 576,000 minute-state observations.
- Confusion matrix states: OFF, STANDBY, WARMUP, IDLE, RUNNING, MAINTENANCE, FAULT.
- Full matrix is in `results/policy_evaluation.json`.

- Planner input ablations (one day per scenario at 08:00):
  - **S1:** no_cv: 2 recommendations, 2 passing constraints; cv_100: 2 recommendations, 2 passing constraints; cv_92: 2 recommendations, 2 passing constraints; cv_80: 1 recommendations, 1 passing constraints.
  - **S2:** no_cv: 0 recommendations, 0 passing constraints; cv_100: 0 recommendations, 0 passing constraints; cv_92: 0 recommendations, 0 passing constraints; cv_80: 0 recommendations, 0 passing constraints.
  - **S3:** no_cv: 1 recommendations, 1 passing constraints; cv_100: 1 recommendations, 1 passing constraints; cv_92: 1 recommendations, 1 passing constraints; cv_80: 1 recommendations, 1 passing constraints.
  - **S4:** no_cv: 0 recommendations, 0 passing constraints; cv_100: 0 recommendations, 0 passing constraints; cv_92: 0 recommendations, 0 passing constraints; cv_80: 0 recommendations, 0 passing constraints.

## Limitations and failures

- Synthetic results only; tariff and emissions remain illustrative assumptions.
- P1 is alert-only and therefore has the same plant KPIs as P0.
- The optimizer is replanned at three 4-hour checkpoints, not every 5 minutes.
- DEFER_JOB proposals are excluded from plant actuation because the command type has no reschedule payload.
- Policy P2 is intentionally naive and may harm schedule readiness; P3 is constraint-checked but not guaranteed to win.
- CV planner-input ablations are one representative day per scenario at the 08:00 checkpoint; they measure recommendation outputs, not plant-actuated outcomes.
- Confidence intervals use a normal approximation over paired seed-level outcomes; for 20 seeds they are descriptive rather than a formal guarantee.
- Full artifacts: `results/policy_evaluation.json`, `results/policy_trials.csv`, and `results/analytics/<scenario>/`.
