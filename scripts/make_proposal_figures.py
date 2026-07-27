#!/usr/bin/env python3
"""Build the preliminary-data figure and statistics table for the proposal.

Reads the manual heater-impulse runs in data/heater-manual/, extracts thermal and
humidity time constants, estimates the frequency response by deconvolving the
known rectangular heat pulse, and writes:

    docs/proposal/figures/fig_preliminary_impulse.{png,pdf}
    docs/proposal/figures/table_preliminary_stats.csv

Run from the repository root:  python3 scripts/make_proposal_figures.py
"""

import csv
import math
import statistics
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FixedFormatter, FixedLocator, NullFormatter  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HM = ROOT / "data" / "heater-manual"
OUT = ROOT / "docs" / "proposal" / "figures"

# Keeper runs only. Discarded: Al_r3/Al_r4 (late onset), fan_r1 (unsettled pre-impulse),
# baseline_6V_r4 (aborted).
KEEPERS = [
    ("baseline", "B_r1", "baseline_6V_r1_20260726_202621.csv"),
    ("baseline", "B_r2", "baseline_6V_r2_20260726_203100.csv"),
    ("baseline", "B_r3", "baseline_6V_r3_20260726_203410.csv"),
    ("baseline", "B_r5", "baseline_6V_r5_20260726_213043.csv"),
    ("Al", "Al_r1", "obstruction_Al_r1_20260726_203930.csv"),
    ("Al", "Al_r2", "obstruction_Al_r2_20260726_204347.csv"),
    ("fan", "fan_r2", "airflow_fan_r2_20260726_212013.csv"),
    ("fan", "fan_r3", "airflow_fan_r3_20260726_212501.csv"),
    ("fan", "fan_r4", "airflow_fan_r4_20260726_212748.csv"),
    ("bag", "bag_r1", "obstruction_bag_r1_20260726_213403.csv"),
]

CONDS = ["baseline", "Al", "fan", "bag"]
COL = {"baseline": "#1f77b4", "Al": "#8c8c8c", "fan": "#d62728", "bag": "#2ca02c"}
NAME = {"baseline": "Baseline", "Al": "Al plate", "fan": "Airflow (fan)", "bag": "Sealed bag"}
MK = {"baseline": "o", "Al": "s", "fan": "^", "bag": "D"}

PULSE_S = 10.0  # commanded heater on-time
GRID = np.arange(-8, 95, 0.5)  # common time axis, aligned to heat onset
FGRID = np.logspace(math.log10(0.002), math.log10(0.05), 120)


def analyze(path):
    rows = list(csv.DictReader(path.open()))
    t = np.array([float(r["t_s"]) for r in rows])
    T = np.array([float(r["temp_F"]) for r in rows])
    RH = np.array([float(r["humidity"]) for r in rows])

    rough0 = T[t < 3].mean()
    onset = None
    for i in range(len(t) - 3):
        if np.all(T[i : i + 3] - rough0 >= 0.15):
            onset = float(t[i])
            break
    if onset is None:
        raise ValueError(f"no heat onset detected in {path.name}")

    # Baseline window ends just before onset so an early pulse cannot bias T0.
    cut = max(onset - 1.0, 2.0) if onset < 12 else 10.5
    pre = t <= cut
    T0, RH0 = T[pre].mean(), RH[pre].mean()
    dT, dRH = T - T0, RH - RH0

    pi = int(np.argmax(dT))
    peak = float(dT[pi])
    asym = float(dT[(t >= 100) & (t <= 120)].mean())

    oi = int(np.argmin(np.abs(t - onset)))
    tau_heat = None
    tgt = dT[oi] + 0.632 * (peak - dT[oi])
    for i in range(oi, pi + 1):
        if dT[i] >= tgt:
            tau_heat = float(t[i] - t[oi])
            break

    tau_cool = None
    tgt = asym + 0.368 * (peak - asym)
    for i in range(pi, len(dT)):
        if dT[i] <= tgt:
            tau_cool = float(t[i] - t[pi])
            break

    mi = int(np.argmin(dRH))
    tau_dry = None
    rh_peak_i = int(np.argmax(dRH[: mi + 1])) if mi > 0 else 0
    tgt = dRH[rh_peak_i] + 0.632 * (dRH[mi] - dRH[rh_peak_i])
    for i in range(rh_peak_i, mi + 1):
        if dRH[i] <= tgt:
            tau_dry = float(t[i] - t[rh_peak_i])
            break

    d = dict(
        t=t, dT=dT, dRH=dRH, onset=onset, peak=peak, asym=asym,
        tau_heat=tau_heat, tau_cool=tau_cool, tau_dry=tau_dry,
        rh_dip=float(dRH[mi]), T0=T0, RH0=RH0,
    )
    tt = t - onset
    d["h_t"] = np.interp(GRID, tt, dT, left=np.nan, right=np.nan)
    d["h_rh"] = np.interp(GRID, tt, dRH, left=np.nan, right=np.nan)
    return d


def transfer_function(d, reg=0.03):
    """Regularized deconvolution of the rectangular heat pulse: H = Y U* / (|U|^2 + eps)."""
    t, dT = d["t"], d["dT"]
    dt = float(np.median(np.diff(t)))
    u = np.zeros_like(t)
    u[(t >= d["onset"]) & (t < d["onset"] + PULSE_S)] = 1.0
    nfft = 1 << int(math.ceil(math.log2(len(t) * 4)))
    Y = np.fft.rfft(dT, n=nfft)
    U = np.fft.rfft(u, n=nfft)
    f = np.fft.rfftfreq(nfft, d=dt)
    eps = (reg * np.abs(U).max()) ** 2
    H = Y * np.conj(U) / (np.abs(U) ** 2 + eps)
    m = (f > 0) & (f <= 0.05)
    mag = np.interp(FGRID, f[m], np.abs(H[m]))
    return mag / mag[:5].mean()


def load_offsets():
    p = HM / "preliminary_keepers_summary.csv"
    return {r["label"]: r for r in csv.DictReader(p.open())}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    offsets = load_offsets()

    runs = []
    for cond, label, fname in KEEPERS:
        d = analyze(HM / fname)
        d.update(cond=cond, label=label, file=fname)
        d["H_norm"] = transfer_function(d)
        d["fc_mHz"] = 1e3 / (2 * math.pi * d["tau_cool"])
        s = offsets[label]
        d["off_T"] = float(s["offset_T_F"])
        d["off_RH"] = float(s["offset_RH_pct"])
        d["start_utc"] = s["start_utc"]
        runs.append(d)

    write_table(runs)
    make_figure(runs)


def write_table(runs):
    keys = ["peak", "tau_heat", "tau_cool", "tau_dry", "rh_dip", "fc_mHz", "off_T", "off_RH"]
    path = OUT / "table_preliminary_stats.csv"
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["condition", "n"] + [f"{k}_{s}" for k in keys for s in ("mean", "sd")])
        for c in CONDS:
            g = [d for d in runs if d["cond"] == c]
            row = [c, len(g)]
            for k in keys:
                v = [d[k] for d in g if d[k] is not None]
                row += [round(statistics.mean(v), 3), round(statistics.stdev(v), 3) if len(v) > 1 else 0.0]
            w.writerow(row)
    print(f"wrote {path}")
    for c in CONDS:
        g = [d for d in runs if d["cond"] == c]
        m = lambda k: statistics.mean(d[k] for d in g if d[k] is not None)  # noqa: E731
        print(
            f"  {c:<9} n={len(g)}  peak={m('peak'):.2f}F  tau_heat={m('tau_heat'):.1f}s  "
            f"tau_cool={m('tau_cool'):.1f}s  fc={m('fc_mHz'):.2f}mHz  "
            f"offT={m('off_T'):+.2f}F  offRH={m('off_RH'):+.2f}%"
        )


def make_figure(runs):
    plt.rcParams.update({
        "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8.5,
        "legend.fontsize": 6.8, "xtick.labelsize": 7, "ytick.labelsize": 7,
        "axes.linewidth": 0.8, "lines.linewidth": 1.2,
    })
    fig, axes = plt.subplots(2, 2, figsize=(7.1, 5.2))

    # (a) time-domain impulse response
    ax = axes[0, 0]
    handles = []
    for c in CONDS:
        g = [d for d in runs if d["cond"] == c]
        M = np.vstack([d["h_t"] for d in g])
        if len(g) > 1:
            ax.fill_between(GRID, np.nanmin(M, 0), np.nanmax(M, 0), color=COL[c], alpha=0.18, lw=0)
        ax.plot(GRID, np.nanmean(M, 0), color=COL[c])
        handles.append(Line2D([], [], color=COL[c], marker=MK[c], ms=4.5, mec="white",
                              mew=0.6, label=f"{NAME[c]} (n={len(g)})"))
    ax.axvspan(0, PULSE_S, color="orange", alpha=0.13, lw=0)
    ax.text(PULSE_S / 2, 2.74, "heat", ha="center", fontsize=6.5, color="#b06000")
    ax.set_xlim(-8, 90)
    ax.set_ylim(-0.25, 2.95)
    ax.set_xlabel("time since heat onset (s)")
    ax.set_ylabel(r"$\Delta T$ (°F)")
    ax.set_title("(a)  Thermal impulse response $h(t)$", loc="left")
    ax.legend(handles=handles, frameon=False, loc="upper right")
    ax.grid(alpha=0.25, lw=0.5)

    # (b) frequency response
    ax = axes[0, 1]
    fm = np.logspace(math.log10(2), math.log10(20), 200)
    f_mHz = FGRID * 1e3
    sel = (f_mHz >= 2) & (f_mHz <= 20)
    for c in CONDS:
        g = [d for d in runs if d["cond"] == c]
        M = np.vstack([d["H_norm"] for d in g])[:, sel]
        if len(g) > 1:
            ax.fill_between(f_mHz[sel], np.nanmin(M, 0), np.nanmax(M, 0), color=COL[c], alpha=0.16, lw=0)
        ax.loglog(f_mHz[sel], np.nanmean(M, 0), color=COL[c])
        tau = statistics.mean(d["tau_cool"] for d in g)
        ax.loglog(fm, 1 / np.sqrt(1 + (2 * np.pi * fm * 1e-3 * tau) ** 2),
                  color=COL[c], ls="--", lw=0.9, alpha=0.75)
        ax.plot([1e3 / (2 * np.pi * tau)], [1 / math.sqrt(2)], marker="o", ms=4,
                color=COL[c], mec="white", mew=0.6, zorder=6)
    ax.set_xlim(2, 20)
    ax.set_ylim(6e-2, 1.9)
    ax.xaxis.set_major_locator(FixedLocator([2, 3, 5, 10, 20]))
    ax.xaxis.set_major_formatter(FixedFormatter(["2", "3", "5", "10", "20"]))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_xlabel("frequency (mHz)")
    ax.set_ylabel(r"$|H(\omega)|\,/\,|H(0)|$")
    ax.set_title(r"(b)  $|H(\omega)|$: measured (—) vs. 1$^{\rm st}$-order (- -)", loc="left")
    ax.grid(alpha=0.25, which="both", lw=0.5)
    ax.annotate("corner $f_c$ +31%\nwith airflow", xy=(5.73, 0.707), xytext=(9.5, 1.45),
                fontsize=6.4, color="#d62728", ha="center",
                arrowprops=dict(arrowstyle="->", color="#d62728", lw=0.8))

    # (c) passive vs active discriminant
    ax = axes[1, 0]
    ax.axhspan(34.0, 39.5, color="#1f77b4", alpha=0.07, lw=0)
    ax.axhspan(24.5, 30.5, color="#d62728", alpha=0.07, lw=0)
    for c in CONDS:
        g = [d for d in runs if d["cond"] == c]
        ax.scatter([d["off_T"] for d in g], [d["tau_cool"] for d in g], s=44, marker=MK[c],
                   color=COL[c], edgecolor="white", linewidth=0.7, zorder=4, clip_on=False)
    b5 = next(d for d in runs if d["label"] == "B_r5")
    ax.annotate("undisturbed, 3 min after fan off:\nDC bias still fault-like, "
                r"$\tau_{\rm cool}$ healthy",
                xy=(b5["off_T"], b5["tau_cool"]), xytext=(-2.05, 32.6),
                fontsize=6.3, color="#1f77b4", ha="left", va="center",
                arrowprops=dict(arrowstyle="->", color="#1f77b4", lw=0.8))
    ax.text(-0.20, 38.9, "nominal band", fontsize=6.4, color="#1f77b4", ha="right", va="center")
    ax.text(-0.20, 25.1, "airflow band", fontsize=6.4, color="#d62728", ha="right", va="center")
    ax.set_xlim(-2.8, -0.12)
    ax.set_ylim(24.5, 39.5)
    ax.set_xlabel(r"passive DC bias  $T_{\rm node}-\overline{T}_{\rm room}$ (°F)")
    ax.set_ylabel(r"active $\tau_{\rm cool}$ (s)")
    ax.set_title("(c)  Passive DC bias vs. active time constant", loc="left")
    ax.grid(alpha=0.25, lw=0.5)

    # (d) humidity channel
    ax = axes[1, 1]
    for c in CONDS:
        g = [d for d in runs if d["cond"] == c]
        M = np.vstack([d["h_rh"] for d in g])
        if len(g) > 1:
            ax.fill_between(GRID, np.nanmin(M, 0), np.nanmax(M, 0), color=COL[c], alpha=0.16, lw=0)
        ax.plot(GRID, np.nanmean(M, 0), color=COL[c])
    ax.axvspan(0, PULSE_S, color="orange", alpha=0.13, lw=0)
    ax.axhline(0, color="0.5", lw=0.6)
    ax.set_xlim(-8, 90)
    ax.set_xlabel("time since heat onset (s)")
    ax.set_ylabel(r"$\Delta$RH (%)")
    ax.set_title("(d)  Coupled humidity response", loc="left")
    ax.grid(alpha=0.25, lw=0.5)

    fig.tight_layout(pad=0.6, w_pad=1.3, h_pad=1.0)
    for ext in ("png", "pdf"):
        p = OUT / f"fig_preliminary_impulse.{ext}"
        fig.savefig(p, dpi=220)
        print(f"wrote {p}")


if __name__ == "__main__":
    main()
