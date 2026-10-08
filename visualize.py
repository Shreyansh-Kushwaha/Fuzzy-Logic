"""
visualize.py
============

All plots for the project. Every function returns a matplotlib Figure so the
same code serves main.py (saved as PNG), the PDF report and the Streamlit
dashboard (st.pyplot).

    plot_membership(var_name, value=None, variables=None)  one variable's MFs
    plot_all_membership(temp, hum, fis=None)               2x2 grid for the dashboard
    plot_control_surface(output, data)                     3D surface temperature x humidity -> output
    plot_surface_heatmap(output, fis=None, point=None)     2D map of the same surface (editor)
    plot_pi_surface()                                      3D surface of the Fuzzy PI rule base
    plot_worked_example(temp, hum, fis=None)               fuzzification, rules, aggregation, centroid
    plot_aggregated(result)                                aggregated output sets with centroid lines
    plot_simulation(results)                               temperature + ac_power vs time, any controllers
    plot_energy_bars(rows)                                 kWh per scenario and controller
    save_figure(fig, path)                                 save PNG and close
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")  # headless backend: works in scripts, CI and Streamlit

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402
from mpl_toolkits.mplot3d import Axes3D  # noqa: E402,F401  (registers the 3d projection)

import fuzzy_controller as fc  # noqa: E402
import fuzzy_pi as fp  # noqa: E402
from simulation import COMFORT_HIGH, COMFORT_LOW, SETPOINT  # noqa: E402

# ---------------------------------------------------------------------------
# Style: recessive chrome, thin marks, fixed colour roles
# ---------------------------------------------------------------------------
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"

# Categorical slots, assigned in fixed order (validated as a set, first three all-pairs)
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
CONTROLLER_COLORS = {
    "Fuzzy (Mamdani)": CAT[0],      # blue
    "ON/OFF thermostat": CAT[1],    # orange
    "Fuzzy PI": CAT[2],             # aqua
}
FUZZY_COLOR = CAT[0]
ONOFF_COLOR = CAT[1]
PI_COLOR = CAT[2]
COMFORT_FILL = "#898781"            # neutral band, so no series colour is reused

# ac_power terms are ordered heat -> off -> cool, so they get a diverging
# red <-> gray <-> blue encoding; dashes separate strong vs mild terms.
AC_STYLE = {
    "strong_heat": ("#e34948", "-"),
    "mild_heat":   ("#e34948", "--"),
    "off":         ("#898781", "-"),
    "mild_cool":   ("#2a78d6", "--"),
    "strong_cool": ("#2a78d6", "-"),
}

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "axes.titleweight": "bold",
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "axes.grid": True,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2,
    "legend.frameon": False,
    "legend.fontsize": 9,
    "lines.linewidth": 2.0,
    "font.size": 10,
})


def controller_color(name: str, idx: int = 0) -> str:
    return CONTROLLER_COLORS.get(name, CAT[(idx + 3) % len(CAT)])


def _mf_style(var_name: str, term: str, idx: int) -> tuple[str, str]:
    if var_name == "ac_power" and term in AC_STYLE:
        return AC_STYLE[term]
    return CAT[idx % len(CAT)], "-"


def save_figure(fig, path: str, dpi: int = 150) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Membership functions
# ---------------------------------------------------------------------------
def _draw_membership(ax, var_name: str, value: float | None = None, variables: dict | None = None) -> None:
    var = (variables or fc.VARIABLES)[var_name]
    x = var["universe"]
    for i, (term, mf) in enumerate(var["mfs"].items()):
        color, ls = _mf_style(var_name, term, i)
        kind, params = var["defs"][term]
        ax.plot(x, mf, color=color, linestyle=ls, label=f"{term}  {kind}{[float(p) for p in params]}")
    if value is not None:
        ax.axvline(value, color=INK, linewidth=1.2, linestyle=":")
        degrees = fc.fuzzify(value, x, var["mfs"])
        for i, (term, mu) in enumerate(degrees.items()):
            if mu > 0:
                color, _ = _mf_style(var_name, term, i)
                ax.plot([value], [mu], "o", markersize=8, color=color,
                        markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=5)
                ax.annotate(f"μ={mu:.2f}", (value, mu), textcoords="offset points",
                            xytext=(6, 4), fontsize=8, color=INK_2)
    ax.set_xlim(x[0], x[-1])
    ax.set_ylim(-0.02, 1.12)
    ax.set_xlabel(var["label"])
    ax.set_ylabel("Membership degree μ")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)


def plot_membership(var_name: str, value: float | None = None, variables: dict | None = None):
    """One figure with every membership function of one variable."""
    fig, ax = plt.subplots(figsize=(8, 4.2))
    _draw_membership(ax, var_name, value, variables)
    ax.set_title(f"Membership functions — {var_name}")
    fig.tight_layout()
    return fig


def plot_all_membership(temp: float | None = None, hum: float | None = None, fis: fc.RoomFIS | None = None):
    """2x2 grid: inputs with the current reading marked, outputs with centroids."""
    fis = fis or fc.DEFAULT_FIS
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5))
    res = fis.infer(temp, hum) if temp is not None and hum is not None else None
    _draw_membership(axes[0, 0], "temperature", None if res is None else res.temperature, fis.variables)
    _draw_membership(axes[0, 1], "humidity", None if res is None else res.humidity, fis.variables)
    _draw_membership(axes[1, 0], "ac_power", variables=fis.variables)
    _draw_membership(axes[1, 1], "fan_speed", variables=fis.variables)
    if res is not None:
        _shade_output(axes[1, 0], fis.ac_power.universe, res.ac_aggregated, res.ac_power)
        _shade_output(axes[1, 1], fis.fan_speed.universe, res.fan_aggregated, res.fan_speed)
    for ax, name in zip(axes.flat, ["temperature", "humidity", "ac_power", "fan_speed"]):
        ax.set_title(name)
    fig.tight_layout()
    return fig


def _shade_output(ax, universe, aggregated, crisp):
    ax.fill_between(universe, 0, aggregated, color=INK_2, alpha=0.18, label="aggregated output", zorder=0)
    ax.axvline(crisp, color=INK, linewidth=1.5)
    ax.annotate(f"centroid = {crisp:.2f}", (crisp, 1.05), textcoords="offset points",
                xytext=(4, 0), fontsize=9, color=INK, fontweight="bold")


# ---------------------------------------------------------------------------
# Control surfaces
# ---------------------------------------------------------------------------
def control_surface_data(fis: fc.RoomFIS | None = None, t_step: float = 0.5, h_step: float = 1.0):
    """Evaluate the FIS on a grid (vectorised). Returns (T grid, H grid, ac grid, fan grid)."""
    fis = fis or fc.DEFAULT_FIS
    t_vals = np.arange(fc.TEMP_RANGE[0], fc.TEMP_RANGE[1] + 1e-9, t_step)
    h_vals = np.arange(fc.HUM_RANGE[0], fc.HUM_RANGE[1] + 1e-9, h_step)
    T, H = np.meshgrid(t_vals, h_vals)
    AC, FAN = fis.compute_many(T, H)
    return T, H, AC, FAN


def _surface_style(output: str):
    if output == "ac_power":
        return "RdBu", (-100, 100), "AC power (%)"   # red = heating, blue = cooling
    return "Blues", (0, 100), "Fan speed (%)"


def plot_control_surface(output: str, data=None):
    """3D surface temperature x humidity -> output ('ac_power' or 'fan_speed')."""
    T, H, AC, FAN = data if data is not None else control_surface_data()
    Z = AC if output == "ac_power" else FAN
    cmap, vlim, zlabel = _surface_style(output)
    fig = plt.figure(figsize=(9, 6.5))
    ax = fig.add_subplot(111, projection="3d")
    surf = ax.plot_surface(T, H, Z, cmap=cmap, vmin=vlim[0], vmax=vlim[1],
                           linewidth=0, antialiased=True, rcount=80, ccount=80)
    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel("Humidity (%RH)")
    ax.set_zlabel(zlabel)
    ax.set_zlim(*vlim)
    ax.view_init(elev=28, azim=-130)
    ax.set_title(f"Control surface — temperature × humidity → {output}")
    fig.colorbar(surf, ax=ax, shrink=0.6, pad=0.1, label=zlabel)
    fig.tight_layout()
    return fig


def plot_surface_heatmap(output: str, fis: fc.RoomFIS | None = None, point=None, ax=None, title=None):
    """2D map of the control surface; `point` = (temp, hum) marks the current input."""
    T, H, AC, FAN = control_surface_data(fis, t_step=0.5, h_step=1.0)
    Z = AC if output == "ac_power" else FAN
    cmap, vlim, zlabel = _surface_style(output)
    own = ax is None
    if own:
        fig, ax = plt.subplots(figsize=(6.5, 4.6))
    mesh = ax.pcolormesh(T, H, Z, cmap=cmap, vmin=vlim[0], vmax=vlim[1], shading="auto")
    levels = [-60, -30, 0, 30, 60] if output == "ac_power" else [20, 40, 60, 80]
    cs = ax.contour(T, H, Z, levels=levels, colors=INK_2, linewidths=0.6)
    ax.clabel(cs, fontsize=7, fmt="%d")
    if point is not None:
        ax.plot([point[0]], [point[1]], "o", markersize=9, color=INK, markeredgecolor=SURFACE, markeredgewidth=1.5)
    ax.set_xlabel("Temperature (°C)")
    ax.set_ylabel("Humidity (%RH)")
    ax.set_title(title or f"{output} map")
    ax.grid(False)
    plt.colorbar(mesh, ax=ax, label=zlabel)
    if own:
        fig.tight_layout()
        return fig
    return None


def plot_pi_surface():
    """3D surface of the Fuzzy PI rule base: (error, change of error) -> Δu."""
    e = np.linspace(-6, 6, 61)
    de = np.linspace(-1, 1, 41)
    E, DE = np.meshgrid(e, de)
    DU = fp.PI_FIS.compute_many(error=E, d_error=DE)["du"]
    fig = plt.figure(figsize=(9, 6.5))
    ax = fig.add_subplot(111, projection="3d")
    surf = ax.plot_surface(E, DE, DU, cmap="RdBu", vmin=-20, vmax=20, linewidth=0, antialiased=True)
    ax.set_xlabel("Error e = T − setpoint (°C)")
    ax.set_ylabel("Change of error Δe (°C/min)")
    ax.set_zlabel("Δu (%/min)")
    ax.view_init(elev=28, azim=-130)
    ax.set_title("Fuzzy PI control surface — (e, Δe) → Δu")
    fig.colorbar(surf, ax=ax, shrink=0.6, pad=0.1, label="Δu (%/min)")
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Worked example
# ---------------------------------------------------------------------------
def plot_aggregated(res: fc.InferenceResult, axes=None, fis: fc.RoomFIS | None = None):
    """Aggregated output sets with every rule's clipped consequent and the centroid."""
    fis = fis or fc.DEFAULT_FIS
    own = axes is None
    if own:
        fig, axes = plt.subplots(1, 2, figsize=(13, 4))
    for ax, name, clipped, agg, crisp in (
        (axes[0], "ac_power", res.ac_clipped, res.ac_aggregated, res.ac_power),
        (axes[1], "fan_speed", res.fan_clipped, res.fan_aggregated, res.fan_speed),
    ):
        var = fis.variables[name]
        universe = var["universe"]
        for i, (term, mf) in enumerate(var["mfs"].items()):
            color, ls = _mf_style(name, term, i)
            ax.plot(universe, mf, color=color, linestyle=ls, linewidth=1.0, alpha=0.45, label=term)
        for k, w in enumerate(res.rule_strengths):
            if w > 0:
                ax.plot(universe, clipped[k], color=INK_2, linewidth=1.0, linestyle=":")
        ax.fill_between(universe, 0, agg, color=FUZZY_COLOR, alpha=0.30, label="aggregated (max)")
        ax.plot(universe, agg, color=FUZZY_COLOR, linewidth=2.0)
        ax.axvline(crisp, color=INK, linewidth=1.6)
        ax.annotate(f"centroid = {crisp:.2f} %", (crisp, 1.04), textcoords="offset points",
                    xytext=(-4, 0), ha="right", fontsize=9, color=INK, fontweight="bold")
        ax.set_xlim(universe[0], universe[-1])
        ax.set_ylim(-0.02, 1.15)
        ax.set_xlabel(var["label"])
        ax.set_ylabel("μ")
        ax.set_title(f"Aggregated output — {name}")
        ax.legend(loc="upper left", fontsize=8)
    if own:
        fig.tight_layout()
        return fig
    return None


def plot_worked_example(temp: float, hum: float, fis: fc.RoomFIS | None = None):
    """Full worked example: fuzzification, rule strengths, aggregation, centroid."""
    fis = fis or fc.DEFAULT_FIS
    res = fis.infer(temp, hum)
    fig = plt.figure(figsize=(15, 9))
    gs = fig.add_gridspec(2, 3, height_ratios=[1, 1])
    ax_t = fig.add_subplot(gs[0, 0])
    ax_h = fig.add_subplot(gs[0, 1])
    ax_r = fig.add_subplot(gs[0, 2])
    ax_ac = fig.add_subplot(gs[1, 0:2])
    ax_fan = fig.add_subplot(gs[1, 2])

    _draw_membership(ax_t, "temperature", res.temperature, fis.variables)
    ax_t.set_title(f"1. Fuzzify temperature = {res.temperature:g} °C")
    ax_t.legend(fontsize=7, loc="center left")
    _draw_membership(ax_h, "humidity", res.humidity, fis.variables)
    ax_h.set_title(f"1. Fuzzify humidity = {res.humidity:g} %")
    ax_h.legend(fontsize=7, loc="center left")

    labels = [f"R{r[0]}" for r in fis.rules]
    colors = [FUZZY_COLOR if w > 0 else GRID for w in res.rule_strengths]
    ax_r.bar(labels, res.rule_strengths, color=colors, width=0.6)
    for i, w in enumerate(res.rule_strengths):
        if w > 0:
            ax_r.text(i, w + 0.02, f"{w:.2f}", ha="center", fontsize=9, color=INK)
    ax_r.set_ylim(0, 1.15)
    ax_r.set_ylabel("Firing strength w = min(μT, μH)")
    ax_r.set_title("2. Rule firing strengths (AND = min)")
    ax_r.grid(axis="x", visible=False)

    plot_aggregated(res, axes=[ax_ac, ax_fan], fis=fis)
    ax_ac.set_title("3–4. ac_power: min-implication, max-aggregation, centroid")
    ax_fan.set_title("3–4. fan_speed")
    fig.suptitle(f"Worked example — T = {temp} °C, H = {hum} %  →  "
                 f"ac_power = {res.ac_power:.2f} %, fan_speed = {res.fan_speed:.2f} %",
                 fontsize=13, fontweight="bold", color=INK)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
def _spans(mask: np.ndarray):
    """(start, end) index pairs of consecutive True runs."""
    spans, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(mask)))
    return spans


def plot_simulation(results, title: str | None = None):
    """
    Temperature (top) and AC power (bottom) vs time for any number of
    controllers on the same scenario. Comfort band shaded; for scenarios with
    a schedule the occupied hours are marked; daily runs use a clock axis.
    """
    first = results[0]
    sc = first.scenario
    daily = sc.duration > 180
    t = first.time / 60.0 + sc.start_minute / 60.0 if daily else first.time
    t_act = t[:-1]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7.5), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 2]})

    ax1.axhspan(COMFORT_LOW, COMFORT_HIGH, color=COMFORT_FILL, alpha=0.13,
                label=f"Comfort zone {COMFORT_LOW:g}–{COMFORT_HIGH:g} °C")
    ax1.axhline(SETPOINT, color=MUTED, linewidth=1.0, linestyle="--", label=f"Setpoint {SETPOINT} °C")
    ax1.plot(t_act, first.T_out, color=MUTED, linewidth=1.2, linestyle=":", label="Outside temperature")
    if sc.occupied is not None:
        for a, b in _spans(first.occupied):
            for ax in (ax1, ax2):
                ax.axvspan(t_act[a], t_act[b - 1] + (t_act[1] - t_act[0]), color=CAT[3], alpha=0.07, lw=0)
        ax1.plot([], [], color=CAT[3], alpha=0.35, linewidth=8, label="Occupied hours")
    for i, r in enumerate(results):
        c = controller_color(r.controller, i)
        ax1.plot(t, r.T, color=c, label=r.controller)
        if r.noise:
            ax1.plot(t_act, r.T_measured, color=c, linewidth=0.6, alpha=0.35)
    # end-of-line labels, nudged apart so close finishes stay readable
    ends = sorted((r.T[-1], i) for i, r in enumerate(results))
    lo_all = min(min(r.T.min() for r in results), first.T_out.min(), COMFORT_LOW)
    hi_all = max(max(r.T.max() for r in results), first.T_out.max(), COMFORT_HIGH)
    gap = (hi_all - lo_all) * 0.045
    placed = []
    for value, i in ends:
        y = value if not placed else max(value, placed[-1] + gap)
        placed.append(y)
        ax1.text(t[-1] + (t[-1] - t[0]) * 0.006, y, f"{value:.1f} °C", va="center", fontsize=8, color=INK_2)
    ax1.set_ylabel("Room temperature (°C)")
    extras = []
    if first.noise:
        extras.append("sensor noise on (thin lines = readings)")
    if first.occupancy_control:
        extras.append("eco setback when empty")
    ax1.set_title(title or (
        f"Scenario {sc.key}: {sc.name} — T₀={sc.T_start:g} °C, H₀={sc.H_start:g} %, "
        + (f"T_out={sc.T_outside:g}±{sc.T_amp:g} °C" if sc.is_daily else f"T_out={sc.T_outside:g} °C, H_out={sc.H_outside:g} %")
        + (" | " + ", ".join(extras) if extras else "")), fontsize=10)
    ax1.legend(loc="best", fontsize=8)

    ax2.axhline(0, color=AXIS, linewidth=1.0)
    for i, r in enumerate(results):
        ax2.step(t_act, r.ac, where="post", color=controller_color(r.controller, i),
                 label=r.controller, linewidth=1.4 if daily else 2.0)
    ax2.set_ylim(-110, 110)
    ax2.set_ylabel("AC power (%)\n− heat | + cool")
    if daily:
        ax2.set_xlabel("Time of day")
        ax2.xaxis.set_major_locator(MultipleLocator(3))
        ax2.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v) % 24:02d}:00"))
        ax2.set_xlim(t[0], t[-1] + 1.2)
    else:
        ax2.set_xlabel("Time (min)")
        ax2.set_xlim(0, t[-1] + 6)
    ax2.legend(loc="best", fontsize=8)
    fig.tight_layout()
    return fig


def plot_energy_bars(rows: list[dict], value_col: str = "Energy (kWh)"):
    """Grouped bars: one group per scenario, one bar per controller."""
    scenarios = list(dict.fromkeys(r["Scenario"] for r in rows))
    controllers = list(dict.fromkeys(r["Controller"] for r in rows))
    lookup = {(r["Scenario"], r["Controller"]): r[value_col] for r in rows}
    x = np.arange(len(scenarios))
    width = 0.8 / len(controllers)
    fig, ax = plt.subplots(figsize=(11, 4.8))
    for i, c in enumerate(controllers):
        vals = [lookup.get((s, c), np.nan) for s in scenarios]
        bars = ax.bar(x + (i - (len(controllers) - 1) / 2) * width, vals, width * 0.92,
                      color=controller_color(c, i), label=c)
        for b, v in zip(bars, vals):
            if np.isfinite(v):
                ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom",
                        fontsize=7.5, color=INK_2)
    ax.set_xticks(x, scenarios, fontsize=8.5)
    ax.set_ylabel(value_col)
    ax.set_title(f"{value_col} by scenario and controller")
    ax.grid(axis="x", visible=False)
    ax.legend()
    fig.tight_layout()
    return fig
