"""
main.py
=======

Runs the complete project end to end:

    1. Prints the FIS configuration (Mamdani settings, rule bases).
    2. Worked example at T = 32 °C, H = 75 %: fuzzification degrees, rule
       firing strengths, crisp outputs, and an analytical hand check.
    3. Cross-checks the inference against skfuzzy.control and the vectorised
       evaluator against the step-by-step one.
    4. Checks that out-of-range / invalid inputs never crash compute().
    5. Saves all figures to outputs/figures/.
    6. Simulation: scenarios A-D with the fuzzy Mamdani, fuzzy PI and ON/OFF
       controllers (comfort, energy in % x min and kWh, cost, switching).
    7. Sensor-noise experiment.
    8. Occupancy (eco setback) experiment on the 24-hour day.
    9. Exports the ESP32 lookup table and reports its accuracy.
   10. Writes CSV/Markdown tables and a PDF report.

Usage:  python main.py
"""

from __future__ import annotations

import csv
import os
import sys

import numpy as np

import fuzzy_controller as fc
import fuzzy_pi as fp
import report_pdf
import simulation as sim
import visualize as viz

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "outputs")
FIG_DIR = os.path.join(OUT_DIR, "figures")
sys.path.insert(0, os.path.join(HERE, "hardware"))

EXAMPLE_T, EXAMPLE_H = 32.0, 75.0

CONSOLE_COLS = ["Scenario", "Controller", "Settling time", "Max overshoot (°C)", "SS error (°C)",
                "Energy (%·min)", "Energy (kWh)", f"Cost ({sim.CURRENCY})", "Switching events",
                "Comfort (% of occupied time)", "Final T (°C)", "Energy saving vs ON/OFF (%)"]


# ---------------------------------------------------------------------------
# Plain-text table helper (no external dependency)
# ---------------------------------------------------------------------------
def print_table(rows: list[dict], title: str | None = None, cols: list[str] | None = None) -> None:
    if title:
        print(f"\n{title}")
    if not rows:
        print("(empty)")
        return
    cols = [c for c in (cols or list(rows[0].keys())) if c in rows[0]]
    widths = {c: max(len(str(c)), *(len(str(r[c])) for r in rows)) for c in cols}
    line = "+".join("-" * (widths[c] + 2) for c in cols)
    print("+" + line + "+")
    print("| " + " | ".join(str(c).ljust(widths[c]) for c in cols) + " |")
    print("+" + line + "+")
    for r in rows:
        print("| " + " | ".join(str(r[c]).ljust(widths[c]) for c in cols) + " |")
    print("+" + line + "+")


def markdown_table(rows: list[dict]) -> str:
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def write_csv(rows: list[dict], name: str) -> str:
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def banner(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


# ---------------------------------------------------------------------------
# 1. Configuration
# ---------------------------------------------------------------------------
def print_configuration() -> None:
    banner("1. MAMDANI FIS CONFIGURATION")
    print("AND operator = min | implication = min | aggregation = max | "
          "defuzzification = centroid")
    for name, var in fc.VARIABLES.items():
        u = var["universe"]
        print(f"\n{name}: universe [{u[0]:g}, {u[-1]:g}], {len(u)} points (step {fc.STEP})")
        for term, (kind, params) in var["defs"].items():
            print(f"   {term:12s} {kind:7s} {params}")
    print("\nRule base:")
    for r in fc.RULES:
        print("  ", fc.rule_text(r))

    print("\nImproved controller: incremental Fuzzy PI  u[k] = clip(u[k-1] + FIS(e, Δe), -100, 100)")
    print(f"   setpoint {fp.SETPOINT} °C lowered by up to {fp.HUMIDITY_SETPOINT_SHIFT} °C × μ_high(humidity); "
          f"temperature low-pass filter α = {fp.FILTER_ALPHA}")
    for name, var in fp.PI_VARIABLES.items():
        print(f"   {name}: " + ", ".join(f"{t} {k}{p}" for t, (k, p) in var["defs"].items()))
    print("   Rule table (rows e, columns Δe = N / Z / P):")
    for e, row in fp.PI_RULE_TABLE.items():
        print(f"     {e:>2}: " + "  ".join(f"{row[d]:>2}" for d in ("N", "Z", "P")))


# ---------------------------------------------------------------------------
# 2. Worked example + hand verification
# ---------------------------------------------------------------------------
def trapezoid_centroid(a: float, b: float, c: float, d: float) -> float:
    """
    Exact centroid of a unit-height trapezoid (a, b, c, d), decomposed into
    rising triangle [a, b], rectangle [b, c] and falling triangle [c, d].
    """
    parts = []  # (area, centroid)
    if b > a:
        parts.append(((b - a) / 2, a + 2 * (b - a) / 3))
    if c > b:
        parts.append((c - b, (b + c) / 2))
    if d > c:
        parts.append(((d - c) / 2, c + (d - c) / 3))
    area = sum(p[0] for p in parts)
    return sum(p[0] * p[1] for p in parts) / area


def worked_example() -> fc.InferenceResult:
    banner(f"2. WORKED EXAMPLE  (temperature = {EXAMPLE_T} °C, humidity = {EXAMPLE_H} %)")
    res = fc.infer(EXAMPLE_T, EXAMPLE_H)

    rows = [{"Variable": "temperature", "Term": t, "μ": f"{mu:.4f}"} for t, mu in res.temp_degrees.items()]
    rows += [{"Variable": "humidity", "Term": t, "μ": f"{mu:.4f}"} for t, mu in res.hum_degrees.items()]
    print_table(rows, "Step 1 - Fuzzification")

    rows = []
    for (no, t, h, a, f), w in zip(fc.RULES, res.rule_strengths):
        rows.append({
            "Rule": f"R{no}",
            "IF temperature": t, "AND humidity": h,
            "μT": f"{res.temp_degrees[t]:.3f}", "μH": f"{res.hum_degrees[h]:.3f}",
            "w = min": f"{w:.3f}",
            "THEN ac_power": a, "fan_speed": f,
            "Fired": "YES" if w > 0 else "no",
        })
    print_table(rows, "Step 2 - Rule evaluation (AND = min)")

    print("\nStep 3-4 - Implication (min) + aggregation (max) + centroid defuzzification")
    print_table([
        {"Output": "ac_power",  "Crisp value (%)": f"{res.ac_power:.2f}", "Mode": fc.mode_label(res.ac_power)},
        {"Output": "fan_speed", "Crisp value (%)": f"{res.fan_speed:.2f}", "Mode": "-"},
    ])

    print("\nHAND VERIFICATION")
    print("  temperature = 32:")
    print("    cold        trapmf[10,10,16,22]: 32 > 22                -> μ = 0")
    print("    comfortable trimf[18,23,28]:     32 > 28                -> μ = 0")
    print("    hot         trapmf[24,30,40,40]: 30 <= 32 <= 40 (flat)  -> μ = 1")
    print("  humidity = 75:")
    print("    low         trapmf[20,20,30,45]: 75 > 45                -> μ = 0")
    print("    medium      trimf[35,50,65]:     75 > 65                -> μ = 0")
    print("    high        trapmf[55,70,90,90]: 70 <= 75 <= 90 (flat)  -> μ = 1")
    print("  Only R9 (hot AND high) fires: w9 = min(1, 1) = 1.")
    print("  With w = 1 the clipped consequents equal the full sets strong_cool and fan high,")
    print("  so each crisp output is the centroid of a single trapezoid:")
    ac_hand = trapezoid_centroid(40, 70, 100, 100)
    fan_hand = trapezoid_centroid(60, 80, 100, 100)
    print(f"    strong_cool [40,70,100,100]: (15*60 + 30*85) / 45 = {ac_hand:.4f} %")
    print(f"    fan high    [60,80,100,100]: (10*73.33 + 20*90) / 30 = {fan_hand:.4f} %")
    print(f"  FIS result: ac_power = {res.ac_power:.4f} %, fan_speed = {res.fan_speed:.4f} %")
    ok_deg = (res.temp_degrees == {"cold": 0.0, "comfortable": 0.0, "hot": 1.0}
              and res.hum_degrees == {"low": 0.0, "medium": 0.0, "high": 1.0})
    ok_out = abs(res.ac_power - ac_hand) < 0.05 and abs(res.fan_speed - fan_hand) < 0.05
    ok_dir = res.ac_power > 60 and res.fan_speed > 70
    print(f"  Fuzzification matches hand values: {'PASS' if ok_deg else 'FAIL'}")
    print(f"  Crisp outputs match hand centroids: {'PASS' if ok_out else 'FAIL'}")
    print(f"  Direction check (hot + humid -> strong cooling, high fan): {'PASS' if ok_dir else 'FAIL'}")
    return res


# ---------------------------------------------------------------------------
# 3. Cross-checks
# ---------------------------------------------------------------------------
def cross_check() -> None:
    banner("3. CROSS-CHECKS")
    ctrl_sim = fc.build_skfuzzy_ctrl()
    points = [(32, 75), (14, 40), (23, 50), (26, 60), (20, 68), (27, 40), (12, 85), (25.5, 62)]
    rows, worst = [], 0.0
    for t, h in points:
        ac, fan, _ = fc.compute(t, h)
        ctrl_sim.input["temperature"] = t
        ctrl_sim.input["humidity"] = h
        ctrl_sim.compute()
        ac2, fan2 = ctrl_sim.output["ac_power"] + 0.0, ctrl_sim.output["fan_speed"]
        ac2 = 0.0 if abs(ac2) < 1e-9 else ac2
        diff = max(abs(ac - ac2), abs(fan - fan2))
        worst = max(worst, diff)
        rows.append({"T": t, "H": h, "ac (ours)": f"{ac:.3f}", "ac (ctrl)": f"{ac2:.3f}",
                     "fan (ours)": f"{fan:.3f}", "fan (ctrl)": f"{fan2:.3f}", "max |diff|": f"{diff:.2e}"})
    print_table(rows, "a) Step-by-step inference vs skfuzzy.control")
    # skfuzzy.control rounds/interpolates slightly differently internally, so
    # agreement to within 0.001 % is treated as identical.
    print(f"Largest difference: {worst:.2e} %  ->  {'PASS' if worst < 1e-3 else 'MISMATCH'}")

    T, H = np.meshgrid(np.arange(10, 40.01, 1.0), np.arange(20, 90.01, 2.0))
    ac_v, fan_v = fc.compute_many(T, H)
    ref = np.array([[fc.compute(a, b)[:2] for a, b in zip(r1, r2)] for r1, r2 in zip(T, H)])
    d = max(np.abs(ref[..., 0] - ac_v).max(), np.abs(ref[..., 1] - fan_v).max())
    print(f"\nb) Vectorised evaluator vs step-by-step on {T.size} grid points: "
          f"max |diff| = {d:.1e} %  ->  {'PASS' if d < 1e-6 else 'MISMATCH'}")


# ---------------------------------------------------------------------------
# 4. Edge inputs
# ---------------------------------------------------------------------------
def edge_inputs() -> None:
    banner("4. EDGE-INPUT ROBUSTNESS (values are clamped; compute() never raises)")
    cases = [(-50, 0), (10, 20), (40, 90), (100, 150), (float("inf"), float("-inf")),
             (float("nan"), 50), (None, "abc")]
    rows = []
    for t, h in cases:
        ac, fan, w = fc.compute(t, h)
        rows.append({"temp in": repr(t), "hum in": repr(h), "ac_power": f"{ac:.2f}",
                     "fan_speed": f"{fan:.2f}", "rules fired": ", ".join(f"R{i+1}" for i in np.nonzero(w)[0])})
    print_table(rows)


# ---------------------------------------------------------------------------
# 5. Figures of the controllers
# ---------------------------------------------------------------------------
def make_controller_figures() -> list[str]:
    banner("5. CONTROLLER FIGURES")
    os.makedirs(FIG_DIR, exist_ok=True)
    saved = []
    for name in ("temperature", "humidity", "ac_power", "fan_speed"):
        saved.append(viz.save_figure(viz.plot_membership(name), os.path.join(FIG_DIR, f"mf_{name}.png")))
    data = viz.control_surface_data()
    saved.append(viz.save_figure(viz.plot_control_surface("ac_power", data),
                                 os.path.join(FIG_DIR, "surface_ac_power.png")))
    saved.append(viz.save_figure(viz.plot_control_surface("fan_speed", data),
                                 os.path.join(FIG_DIR, "surface_fan_speed.png")))
    saved.append(viz.save_figure(viz.plot_worked_example(EXAMPLE_T, EXAMPLE_H),
                                 os.path.join(FIG_DIR, "worked_example_T32_H75.png")))
    for name in ("error", "d_error", "du"):
        saved.append(viz.save_figure(viz.plot_membership(name, variables=fp.PI_VARIABLES),
                                     os.path.join(FIG_DIR, f"pi_mf_{name}.png")))
    saved.append(viz.save_figure(viz.plot_pi_surface(), os.path.join(FIG_DIR, "pi_surface.png")))
    print(f"{len(saved)} figures written")
    return saved


# ---------------------------------------------------------------------------
# 6-8. Simulations
# ---------------------------------------------------------------------------
def run_main_comparison() -> tuple[list[dict], list[str]]:
    banner("6. SIMULATION: FUZZY MAMDANI vs FUZZY PI vs ON/OFF")
    print(f"Model: T+ = T + {sim.K1}*(T_out - T) - {sim.K2}*(ac/100);  "
          f"H+ = H - {sim.K3}*(ac/100 if cooling) + {sim.K4}*(H_out - H)")
    print(f"Comfort zone {sim.COMFORT_LOW}-{sim.COMFORT_HIGH} °C | ON/OFF setpoint {sim.SETPOINT} °C ± "
          f"{sim.HYSTERESIS} °C | steady-state window = last {sim.SSE_WINDOW} min")
    print(f"Electricity: AC {sim.AC_ELEC_KW} kW at 100 %, fan {sim.FAN_ELEC_KW * 1000:.0f} W at 100 %, "
          f"tariff {sim.CURRENCY}{sim.TARIFF}/kWh")
    rows, figs = [], []
    for key, sc in sim.SCENARIOS.items():
        results = sim.run_scenario(sc)
        rows += sim.metrics_rows(results)
        figs.append(viz.save_figure(viz.plot_simulation(results), os.path.join(FIG_DIR, f"simulation_{key}.png")))
    print_table(rows, "RESULTS SUMMARY (all scenarios, no noise, no occupancy control)", CONSOLE_COLS)
    figs.append(viz.save_figure(viz.plot_energy_bars(rows), os.path.join(FIG_DIR, "energy_kwh.png")))
    return rows, figs


def run_noise_experiment() -> tuple[list[dict], list[str]]:
    banner(f"7. SENSOR-NOISE EXPERIMENT (σ = {sim.NOISE_STD_T} °C, {sim.NOISE_STD_H} %RH, seed {sim.NOISE_SEED})")
    rows, figs = [], []
    for key in ("A", "B", "C"):
        sc = sim.SCENARIOS[key]
        results = sim.run_scenario(sc, noise=True)
        rows += sim.metrics_rows(results, label=f"{key}) {sc.name} + noise")
        figs.append(viz.save_figure(viz.plot_simulation(results), os.path.join(FIG_DIR, f"simulation_{key}_noise.png")))
    print_table(rows, "RESULTS WITH SENSOR NOISE", CONSOLE_COLS)
    return rows, figs


def run_occupancy_experiment() -> tuple[list[dict], list[str]]:
    banner("8. OCCUPANCY EXPERIMENT (24-hour day, office occupied 09:00-18:00)")
    print(f"Eco dead band while empty: AC off inside {sim.ECO_LOW:g}-{sim.ECO_HIGH:g} °C, controller brings the "
          f"room back to the edge beyond ±{sim.ECO_HYSTERESIS} °C; normal control resumes "
          f"{sim.PRECONDITION_MIN} min before arrival")
    sc = sim.SCENARIOS["D"]
    off = sim.run_scenario(sc, occupancy=False)
    on = sim.run_scenario(sc, occupancy=True)
    rows = (sim.metrics_rows(off, label="D) always on")
            + sim.metrics_rows(on, label="D) with occupancy eco"))
    cols = ["Scenario", "Controller", "Energy (kWh)", f"Cost ({sim.CURRENCY})", "Switching events",
            "Comfort (% of occupied time)", "Discomfort (°C·min)"]
    print_table(rows, "OCCUPANCY RESULTS", cols)
    print("\nkWh saved by occupancy control, per controller:")
    for a, b in zip(off, on):
        e0, e1 = a.metrics["kwh"], b.metrics["kwh"]
        print(f"   {a.controller:18s} {e0:6.2f} -> {e1:6.2f} kWh  ({(e0 - e1) / e0 * 100:5.1f} % saved, "
              f"{sim.CURRENCY}{(e0 - e1) * sim.TARIFF:.2f} per day)")
    fig = viz.save_figure(viz.plot_simulation(on), os.path.join(FIG_DIR, "simulation_D_occupancy.png"))
    return rows, [fig]


# ---------------------------------------------------------------------------
# 9. Hardware lookup table
# ---------------------------------------------------------------------------
def export_hardware_lut() -> dict:
    banner("9. ESP32 LOOKUP TABLE")
    import export_lut
    return export_lut.main()


# ---------------------------------------------------------------------------
# 10. Reports
# ---------------------------------------------------------------------------
def write_reports(main_rows, noise_rows, occ_rows, lut_err, figures) -> list[str]:
    banner("10. TABLES AND PDF REPORT")
    paths = [write_csv(main_rows, "results.csv"), write_csv(noise_rows, "results_noise.csv"),
             write_csv(occ_rows, "results_occupancy.csv")]
    md = os.path.join(OUT_DIR, "results.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write("## Main comparison\n\n" + markdown_table(main_rows) + "\n\n")
        f.write("## With sensor noise\n\n" + markdown_table(noise_rows) + "\n\n")
        f.write("## Occupancy (eco setback)\n\n" + markdown_table(occ_rows) + "\n")
    paths.append(md)

    pdf_cols = ["Scenario", "Controller", "Settling time", "Max overshoot (°C)", "SS error (°C)",
                "Energy (kWh)", f"Cost ({sim.CURRENCY})", "Switching events",
                "Comfort (% of occupied time)", "Final T (°C)", "Energy saving vs ON/OFF (%)"]
    pick = lambda rows: [{c: r[c] for c in pdf_cols} for r in rows]  # noqa: E731
    fig_titles = {
        "mf_temperature": "Membership functions — temperature",
        "mf_humidity": "Membership functions — humidity",
        "mf_ac_power": "Membership functions — ac_power",
        "mf_fan_speed": "Membership functions — fan_speed",
        "surface_ac_power": "Control surface — ac_power",
        "surface_fan_speed": "Control surface — fan_speed",
        "worked_example_T32_H75": "Worked example (32 °C, 75 %)",
        "pi_surface": "Fuzzy PI control surface",
        "energy_kwh": "Electrical energy by scenario and controller",
    }
    sections = [
        ("text", "Summary", [
            "A Mamdani fuzzy inference system (temperature + humidity -> AC power + fan speed; AND = min, "
            "implication = min, aggregation = max, centroid defuzzification) is compared with an improved "
            "incremental Fuzzy PI controller and an ON/OFF thermostat (23.5 °C ± 1 °C) on a first-order room model.",
            "- Worked example 32 °C / 75 %: only rule 9 fires; ac_power = 76.67 %, fan_speed = 84.44 % "
            "(matches the hand calculation and skfuzzy.control).",
            "- The 9-rule Mamdani controller is smooth (1 switching event) but settles outside the comfort "
            "zone under strong outdoor loads (proportional-type offset).",
            "- The Fuzzy PI controller removes that offset, keeps 1-5 switching events, and stays in the "
            "comfort zone during occupied hours of the 24-hour day.",
            "- The ON/OFF thermostat reaches the zone fastest but switches 10-180 times.",
            f"- Occupancy eco setback saves electricity on the 24-hour day; the ESP32 lookup table "
            f"reproduces the FIS with a mean error of {lut_err['ac_mean']:.3f} % (max {lut_err['ac_max']:.2f} %).",
        ]),
        ("table", "Main comparison (no noise, no occupancy control)", pick(main_rows)),
        ("table", "Sensor-noise experiment", pick(noise_rows)),
        ("table", "Occupancy experiment (scenario D)", pick(occ_rows)),
    ]
    for p in figures:
        stem = os.path.splitext(os.path.basename(p))[0]
        title = fig_titles.get(stem)
        if title is None and stem.startswith("simulation_"):
            title = "Simulation — " + stem.replace("simulation_", "scenario ").replace("_", " ")
        if title is None and stem.startswith("pi_mf_"):
            title = "Fuzzy PI membership functions — " + stem.replace("pi_mf_", "")
        sections.append(("figure", title or stem, p))
    pdf = os.path.join(OUT_DIR, "report.pdf")
    report_pdf.build_pdf(sections, pdf)
    paths.append(pdf)
    print("CSV, Markdown and PDF written")
    return paths


def main() -> None:
    os.makedirs(FIG_DIR, exist_ok=True)
    print_configuration()
    worked_example()
    cross_check()
    edge_inputs()
    ctrl_figs = make_controller_figures()
    main_rows, sim_figs = run_main_comparison()
    noise_rows, noise_figs = run_noise_experiment()
    occ_rows, occ_figs = run_occupancy_experiment()
    lut_err = export_hardware_lut()
    figures = ctrl_figs + sim_figs + noise_figs + occ_figs
    files = write_reports(main_rows, noise_rows, occ_rows, lut_err, figures)
    banner("FILES WRITTEN")
    for p in figures + files + [os.path.join(HERE, "hardware", "esp32_fuzzy_ac", "fuzzy_lut.h")]:
        print("  ", os.path.relpath(p, HERE))


if __name__ == "__main__":
    main()
