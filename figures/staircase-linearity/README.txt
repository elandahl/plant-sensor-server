Chamber CO₂ staircase figures
=============================

These plots show stepwise 1 mL CO₂ injections into a closed enclosure, as
recorded by NDIR sensors (SCD30 and SCD4x) on Byrn.

Known experimental constants
----------------------------
  V_enc     = 10.21 L     enclosure free volume
  V_dose    = 1.0 mL      pure CO₂ injected each step
  ΔC_ideal  = V_dose / V_enc × 10⁶
            = 0.001 L / 10.21 L × 10⁶
            ≈ 97.94 ppm   expected rise for perfect mix, no leak/sink

Files
-----
  fig_staircase_aug3_runA.png/.pdf
  fig_staircase_aug3_runB.png/.pdf
  fig_staircase_aug4_fan.png/.pdf

Source data: daily CSVs from the lab Pi (Byrne417_01 / _03 / _05).
Frozen or stuck sensors are omitted from a given run.


What each axis is
-----------------
  x — Injection interval index (dimensionless)

      Wall-clock time is mapped so that injection 1 occurs at x = 1, and the
      unit of +1 on the axis is the median time between successive injections
      for that run (about 5 min). Tick labels 1, 2, 3, … mark the injection
      sequence used in the fit. The axis extends beyond that range (no labels)
      so surrounding data before/after the staircase remain visible.

  y — CO₂ recovered, as a fraction of one ideal 1 mL dose

      y = (C − C₀) / ΔC_ideal

      so y = 1 means “sensor reports a cumulative rise equal to one ideal
      closed-tank 1 mL injection.”


Symbol definitions
------------------
  C       Instantaneous (or plateau) CO₂ mole fraction from a given detector,
          in ppm (SCD30: scd30_co2_ppm; SCD4x: scd4x_co2_ppm).

  C₀      Baseline for that detector: mean of its first plateau (before the
          first injection used in the fit). Each sensor has its own C₀.

  ΔC_ideal
          Ideal closed-tank step for one dose, ≈ 97.94 ppm (see above).

  ΔC_obs  Observed step between successive fitted plateaus for a detector
          (ppm). Typically ~63 ppm on SCD30 in these runs.

  x       Injection-interval coordinate (see axes).

  y       (C − C₀) / ΔC_ideal — cumulative recovered dose vs the 1 mL ideal.

  a       Slope of the σ⁻²-weighted linear fit of plateau midpoints:
              y ≈ a · x + b
          Under equal doses, a ≈ mean recovery per injection
              a ≈ ΔC_obs / ΔC_ideal
          e.g. a = 0.63 → ~63% of each 1 mL appears as NDIR Δppm.

  b       Intercept of that same fit (y-intercept). Not forced to zero;
          absorbs small baseline and indexing offsets.

  R²      Coefficient of determination for the weighted fit (closer to 1 =
          more linear stairs).


How the fit is built
--------------------
  1. Detect upward injection steps on SCD30 (monotone level changes).
  2. For each dwell between steps, each detector independently picks a flat
     “plateau” window (settled portion; avoids the rising edge / plume).
  3. Drop the first and last plateaus (edge effects / incomplete dwells).
  4. For remaining plateaus, take (x_mid, y_mean) with
       x_mid = middle of the visual plateau on the injection axis
       y_mean = (plateau_mean_ppm − C₀) / ΔC_ideal
     Weight ≈ 1/σ² using the plateau sample standard deviation σ.
  5. Fit y = a x + b. Darker dots on the plot are the samples inside those
     plateau windows; lighter dots are the rest of the stream.

Dashed grey line: ideal sealed-tank recovery y = x (one full 1 mL per
numbered injection). Vertical distance from a sensor’s fit to that line is
“missing” CO₂ in the reading (mixing, leak, uptake, sensor under-read, etc.).


Reading the figure at a glance
------------------------------
  • Parallel stairs that rise ~0.63 per step → SCD30 recovery ~63%.
  • SCD4x often shows a slightly higher a (~0.74 here) → higher apparent
    sensitivity / recovery vs the same 1 mL truth (not just vs SCD30).
  • High R² → doses and plateaus are linear; good for calibration talk.


Commit / explore note
---------------------
Commit ea56669 stored an earlier y-axis that normalized by the empirical
SCD30 mean step ⟨Δ⟩_SCD30 (good for “unit stairs” / relative linearity).

The working copies here use dose normalization (recovery vs 1 mL / 10.21 L).

Revert figures to the committed ⟨Δ⟩ version:

  git checkout -- figures/staircase-linearity/
