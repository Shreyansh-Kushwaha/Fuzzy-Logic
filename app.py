"""
app.py — Streamlit dashboard for the Mamdani fuzzy room-temperature controller.

Run:  streamlit run app.py            (add --server.port 6000 to pick a port)

Tabs
----
Controller       sidebar sliders -> live outputs, illustrated room, rule
                 firing table, membership plots, control-surface maps,
                 and the Fuzzy PI design.
Live Room        animated rooms side by side (one per controller) with
                 thermometer, humidity dial, AC airflow, ceiling fan,
                 occupancy, and Play / Pause / speed / time slider.
Simulation       graphs and metrics (comfort, kWh, cost, switching) for the
                 scenario chosen in the sidebar.
Rule & MF Editor change any membership function or rule consequent and see
                 the effect on the control surface and the simulation.
Reports          PDF report, CSV, the edited FIS as JSON and an ESP32
                 lookup table for the edited FIS.
"""

from __future__ import annotations

import json
import os
import sys

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import fuzzy_controller as fc
import fuzzy_pi as fp
import report_pdf
import room_view
import simulation as sim
import visualize as viz

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "hardware"))
import export_lut  # noqa: E402

st.set_page_config(page_title="Fuzzy Room Temperature Controller", layout="wide")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _render_png(fig) -> bytes:
    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def default_surface():
    return viz.control_surface_data()


@st.cache_data(show_spinner=False, max_entries=128)
def cached_png(kind: str, temp: float | None = None, hum: float | None = None,
               output: str | None = None, config_json: str | None = None, title: str | None = None) -> bytes:
    """
    Render a figure once and keep the PNG. Figures depend only on the
    arguments, so moving a slider back to a previous value is instant.
    """
    fis = fis_from_config(json.loads(config_json)) if config_json else None
    if kind == "all_membership":
        fig = viz.plot_all_membership(temp, hum, fis=fis)
    elif kind == "heatmap":
        point = (temp, hum) if temp is not None else None
        fig = viz.plot_surface_heatmap(output, fis, point=point, title=title)
    elif kind == "worked":
        fig = viz.plot_worked_example(temp, hum)
    elif kind == "pi_mf":
        fig = viz.plot_membership(output, variables=fp.PI_VARIABLES)
    elif kind == "pi_surface":
        fig = viz.plot_pi_surface()
    else:
        raise ValueError(kind)
    return _render_png(fig)


@st.cache_data(show_spinner=False, max_entries=64)
def sim_png(scenario: sim.Scenario, controllers: tuple, noise: bool, occupancy: bool) -> bytes:
    return _render_png(viz.plot_simulation(cached_run(scenario, controllers, noise, occupancy)))


@st.cache_data(show_spinner=False, max_entries=64)
def edit_sim_png(config_json: str, scenario: sim.Scenario, noise: bool, occupancy: bool) -> bytes:
    return _render_png(viz.plot_simulation(cached_run_custom_fis(config_json, scenario, noise, occupancy)))


def show_png(png: bytes) -> None:
    st.image(png, width="stretch")


def show_html(html: str, height: int) -> None:
    """Render self-contained HTML/JS (st.iframe on new Streamlit, components.html on old)."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        import streamlit.components.v1 as components
        components.html(html, height=height, scrolling=True)


@st.cache_data(show_spinner="Simulating…")
def cached_run(scenario: sim.Scenario, controllers: tuple, noise: bool, occupancy: bool):
    return sim.run_scenario(scenario, controllers, noise=noise, occupancy=occupancy)


@st.cache_data(show_spinner=False)
def cached_run_custom_fis(config_json: str, scenario: sim.Scenario, noise: bool, occupancy: bool):
    cfg = json.loads(config_json)
    fis = fis_from_config(cfg)
    edited = sim.FuzzyController(fis, name="Edited Mamdani")
    default = sim.FuzzyController()
    onoff = sim.OnOffController()
    return [sim.simulate(c, scenario, noise=noise, occupancy=occupancy) for c in (default, edited, onoff)]


def fis_from_config(cfg: dict) -> fc.RoomFIS:
    as_defs = lambda d: {k: (v[0], list(v[1])) for k, v in d.items()}  # noqa: E731
    return fc.RoomFIS(as_defs(cfg["temperature"]), as_defs(cfg["humidity"]),
                      as_defs(cfg["ac_power"]), as_defs(cfg["fan_speed"]),
                      [tuple(r) for r in cfg["rules"]])


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.header("Sensor inputs")
st.sidebar.caption("Drive the Controller tab")
temp = st.sidebar.slider("Temperature (°C)", 10.0, 40.0, 32.0, 0.1)
hum = st.sidebar.slider("Humidity (%RH)", 20.0, 90.0, 75.0, 0.1)

st.sidebar.header("Simulation setup")
st.sidebar.caption("Used by Live Room, Simulation, Editor and Reports")
scenario_options = {f"{k}) {s.name}": k for k, s in sim.SCENARIOS.items()}
scenario_options["Custom"] = "custom"
choice = st.sidebar.selectbox("Scenario", list(scenario_options), index=0)
if scenario_options[choice] == "custom":
    c1, c2 = st.sidebar.columns(2)
    T0 = c1.number_input("Start T (°C)", 10.0, 40.0, 30.0, 0.5)
    H0 = c2.number_input("Start H (%)", 20.0, 90.0, 65.0, 1.0)
    To = c1.number_input("Outside T (°C)", -10.0, 50.0, 32.0, 0.5)
    Ho = c2.number_input("Outside H (%)", 20.0, 90.0, 70.0, 1.0)
    daily = st.sidebar.checkbox("24-hour weather (±6 °C swing, office hours 09–18)", value=False)
    scenario = sim.custom_scenario(T0, H0, To, Ho, daily=daily)
else:
    scenario = sim.SCENARIOS[scenario_options[choice]]

ctrl_keys = st.sidebar.multiselect(
    "Controllers", list(sim.CONTROLLER_LABELS), default=["mamdani", "pi", "onoff"],
    format_func=lambda k: sim.CONTROLLER_LABELS[k])
if not ctrl_keys:
    st.sidebar.warning("Pick at least one controller; showing all three.")
    ctrl_keys = ["mamdani", "pi", "onoff"]
noise = st.sidebar.checkbox(f"Sensor noise (σ = {sim.NOISE_STD_T} °C, {sim.NOISE_STD_H:g} %RH)", value=False)
has_schedule = scenario.occupied is not None
occupancy = st.sidebar.checkbox(
    "Occupancy eco mode (20–27 °C when empty)", value=False, disabled=not has_schedule,
    help="Only for scenarios with occupied hours (D, or Custom with 24-hour weather).")
occupancy = occupancy and has_schedule

st.sidebar.header("Electricity price")
p1, p2 = st.sidebar.columns([2, 1])
tariff = p1.number_input("Tariff per kWh", 0.0, 1000.0, sim.TARIFF, 0.5)
currency = p2.text_input("Currency", sim.CURRENCY, max_chars=4)

results = cached_run(scenario, tuple(ctrl_keys), noise, occupancy)
rows = sim.metrics_rows(results, tariff=tariff, currency=currency)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Mamdani Fuzzy Logic Controller — Room Temperature Regulation")
st.caption("Inputs: temperature & humidity · Outputs: AC power (− heat / + cool) & fan speed · "
           "AND = min · implication = min · aggregation = max · defuzzification = centroid")

tab_ctrl, tab_room, tab_sim, tab_edit, tab_dl = st.tabs(
    ["Controller", "Live Room", "Simulation", "Rule & MF Editor", "Reports & Downloads"])

# ---------------------------------------------------------------------------
# Tab 1 — Controller
# ---------------------------------------------------------------------------
with tab_ctrl:
    res = fc.infer(temp, hum)
    mode = fc.mode_label(res.ac_power)
    c1, c2, c3 = st.columns(3)
    c1.metric("AC power", f"{res.ac_power:+.2f} %")
    c2.metric("Fan speed", f"{res.fan_speed:.2f} %")
    c3.metric("Mode", {"Heating": "🔥 Heating", "Cooling": "❄️ Cooling", "Idle": "⏸️ Idle"}[mode])

    left, right = st.columns([5, 6])
    with left:
        show_html(room_view.static_room_html(res.temperature, res.humidity, res.ac_power, res.fan_speed), 440)
    with right:
        st.subheader("Fuzzification")
        f1, f2 = st.columns(2)
        f1.dataframe([{"Temperature term": k, "μ": round(v, 4)} for k, v in res.temp_degrees.items()],
                     hide_index=True, width="stretch")
        f2.dataframe([{"Humidity term": k, "μ": round(v, 4)} for k, v in res.hum_degrees.items()],
                     hide_index=True, width="stretch")
        st.subheader("Rule evaluation")
        only_fired = st.checkbox("Show only rules that fired", value=False)
        rule_rows = []
        for (no, t, h, a, f), w in zip(fc.RULES, res.rule_strengths):
            if only_fired and w <= 0:
                continue
            rule_rows.append({
                "Rule": f"R{no}", "IF temperature": t, "AND humidity": h,
                "μT": round(res.temp_degrees[t], 3), "μH": round(res.hum_degrees[h], 3),
                "Strength w = min": round(float(w), 3),
                "THEN ac_power": a, "fan_speed": f, "Fired": "✅" if w > 0 else "—",
            })
        st.dataframe(rule_rows, hide_index=True, width="stretch")

    st.subheader("Membership functions (current input marked, aggregated output shaded)")
    show_png(cached_png("all_membership", temp, hum))

    st.subheader("Where this input sits on the control surface")
    m1, m2 = st.columns(2)
    with m1:
        show_png(cached_png("heatmap", res.temperature, res.humidity, "ac_power", title="AC power map"))
    with m2:
        show_png(cached_png("heatmap", res.temperature, res.humidity, "fan_speed", title="Fan speed map"))

    # Toggles (not expanders) so these figures are only computed when opened.
    if st.toggle("Show the worked-example view (rule strengths, clipped sets, centroid)"):
        show_png(cached_png("worked", temp, hum))

    if st.toggle("Show the improved controller: Fuzzy PI (removes the steady-state offset)"):
        st.markdown(
            "The 9-rule Mamdani controller maps the *current* temperature straight to a command, so under "
            "a strong outdoor load it settles slightly outside the comfort zone. The **Fuzzy PI** controller "
            "looks at the error `e = T − setpoint` and how fast it changes `Δe`, and decides how much to "
            "**change** the AC command each minute: `u[k] = clip(u[k−1] + Δu, −100, 100)`. The summation "
            "is the integral action that removes the offset. Its setpoint drops by up to "
            f"{fp.HUMIDITY_SETPOINT_SHIFT} °C when the air is humid, and its temperature reading is "
            f"smoothed (α = {fp.FILTER_ALPHA}) so noise does not upset Δe.")
        st.dataframe(
            [{"e \\ Δe": e, **{d: row[d] for d in ("N", "Z", "P")}} for e, row in fp.PI_RULE_TABLE.items()],
            hide_index=True)
        g1, g2 = st.columns(2)
        with g1:
            show_png(cached_png("pi_mf", output="error"))
            show_png(cached_png("pi_mf", output="du"))
        with g2:
            show_png(cached_png("pi_mf", output="d_error"))
            show_png(cached_png("pi_surface"))

# ---------------------------------------------------------------------------
# Tab 2 — Live Room
# ---------------------------------------------------------------------------
with tab_room:
    st.markdown(
        "Press **Play** to watch each controller run the same room side by side. Walls turn blue when cold "
        "and red when hot; the AC blows **blue** air when cooling and **red** when heating (stronger = "
        "harder); the ceiling fan spins at the fan-speed output. Change the scenario, controllers, noise or "
        "occupancy in the sidebar.")
    show_html(room_view.room_html(results), 780)

# ---------------------------------------------------------------------------
# Tab 3 — Simulation
# ---------------------------------------------------------------------------
with tab_sim:
    sc = results[0].scenario
    st.subheader(f"Scenario {sc.key}: {sc.name}")
    st.caption(
        f"Model (1-min step, {sc.duration} min): T+ = T + {sim.K1}·(T_out − T) − {sim.K2}·(ac/100); "
        f"H+ = H − {sim.K3}·(ac/100 if cooling) + {sim.K4}·(H_out − H). Comfort zone "
        f"{sim.COMFORT_LOW:g}–{sim.COMFORT_HIGH:g} °C; ON/OFF setpoint {sim.SETPOINT} °C ± {sim.HYSTERESIS:g} °C. "
        f"Electricity: AC {sim.AC_ELEC_KW} kW at 100 %, fan {sim.FAN_ELEC_KW * 1000:.0f} W."
        + (" Sensor noise ON." if noise else "") + (" Occupancy eco mode ON." if occupancy else ""))
    cols = st.columns(len(results))
    for col, r in zip(cols, results):
        m = r.metrics
        col.markdown(f"**{r.controller}**")
        col.metric("Energy", f"{m['kwh']:.2f} kWh", f"{currency}{m['kwh'] * tariff:.2f}", delta_color="off")
        col.metric("Comfort while occupied", f"{m['comfort_occupied_pct']:.0f} %")
        col.metric("Switching events", f"{m['switching_events']}")
    show_png(sim_png(scenario, tuple(ctrl_keys), noise, occupancy))
    st.subheader("Metrics")
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("Settling time = first minute after which T stays in 22–25 °C until the end. "
               "Overshoot = excursion past 23.5 °C on the side opposite to the start. "
               f"Steady-state error = mean |T − 23.5| over the last {sim.SSE_WINDOW} min. "
               "Energy (%·min) = Σ|ac_power|; kWh adds the fan. Switching events = changes between "
               f"heating / idle / cooling (|ac| < {fc.MODE_THRESHOLD:g} % counts as idle). "
               "Discomfort = °C·min outside 22–25 °C while occupied.")

# ---------------------------------------------------------------------------
# Tab 4 — Rule & MF editor
# ---------------------------------------------------------------------------
EDIT_KEYS = ["edit_temperature", "edit_humidity", "edit_ac_power", "edit_fan_speed", "edit_rules"]


def mf_frame(defs: dict) -> pd.DataFrame:
    rows_ = []
    for term, (kind, p) in defs.items():
        p = [float(v) for v in p] + [None] * (4 - len(p))
        rows_.append({"Term": term, "Type": kind, "a": p[0], "b": p[1], "c": p[2], "d": p[3]})
    return pd.DataFrame(rows_)


def frame_to_defs(df: pd.DataFrame) -> dict:
    defs = {}
    for _, r in df.iterrows():
        n = fc.MF_PARAM_COUNT.get(r["Type"], 4)
        params = [r[c] for c in ("a", "b", "c", "d")[:n]]
        defs[r["Term"]] = (r["Type"], [float("nan") if v is None or pd.isna(v) else float(v) for v in params])
    return defs


with tab_edit:
    st.markdown(
        "Change any membership function (a ≤ b ≤ c ≤ d, inside the universe; triangles use a, b, c) or "
        "any rule's consequents, then compare the edited controller with the original on the control "
        "surface and in the scenario chosen in the sidebar.")
    if st.button("Reset editor to the original design"):
        for k in EDIT_KEYS:
            st.session_state.pop(k, None)
        st.rerun()

    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Temperature (°C) — universe 10…40**")
        t_df = st.data_editor(mf_frame(fc.TEMP_MF_DEFS), key="edit_temperature", hide_index=True,
                              disabled=["Term", "Type"], width="stretch")
        st.markdown("**AC power (%) — universe −100…100**")
        a_df = st.data_editor(mf_frame(fc.AC_MF_DEFS), key="edit_ac_power", hide_index=True,
                              disabled=["Term", "Type"], width="stretch")
    with e2:
        st.markdown("**Humidity (%RH) — universe 20…90**")
        h_df = st.data_editor(mf_frame(fc.HUM_MF_DEFS), key="edit_humidity", hide_index=True,
                              disabled=["Term", "Type"], width="stretch")
        st.markdown("**Fan speed (%) — universe 0…100**")
        f_df = st.data_editor(mf_frame(fc.FAN_MF_DEFS), key="edit_fan_speed", hide_index=True,
                              disabled=["Term", "Type"], width="stretch")

    st.markdown("**Rules** (pick new consequents)")
    rules_df = pd.DataFrame([{"Rule": f"R{no}", "Temperature": t, "Humidity": h, "AC power": a, "Fan speed": f}
                             for no, t, h, a, f in fc.RULES])
    r_df = st.data_editor(
        rules_df, key="edit_rules", hide_index=True, width="stretch",
        disabled=["Rule", "Temperature", "Humidity"],
        column_config={
            "AC power": st.column_config.SelectboxColumn(options=list(fc.AC_MF_DEFS), required=True),
            "Fan speed": st.column_config.SelectboxColumn(options=list(fc.FAN_MF_DEFS), required=True),
        })

    edited_defs = {
        "temperature": (frame_to_defs(t_df), fc.TEMP_RANGE),
        "humidity": (frame_to_defs(h_df), fc.HUM_RANGE),
        "ac_power": (frame_to_defs(a_df), fc.AC_RANGE),
        "fan_speed": (frame_to_defs(f_df), fc.FAN_RANGE),
    }
    problems = []
    for name, (defs, (lo, hi)) in edited_defs.items():
        problems += [f"{name} → {p}" for p in fc.validate_mf_defs(defs, lo, hi)]
    edited_rules = [(i + 1, r["Temperature"], r["Humidity"], r["AC power"], r["Fan speed"])
                    for i, r in r_df.iterrows()]

    if problems:
        st.error("The edited design is not valid yet, so the original is shown:\n\n- " + "\n- ".join(problems))
        edited_fis = fc.DEFAULT_FIS
    else:
        edited_fis = fc.RoomFIS(edited_defs["temperature"][0], edited_defs["humidity"][0],
                                edited_defs["ac_power"][0], edited_defs["fan_speed"][0], edited_rules)
    config = edited_fis.as_config()
    st.session_state["edited_config"] = config
    changed = json.dumps(config, sort_keys=True) != json.dumps(fc.DEFAULT_FIS.as_config(), sort_keys=True)
    st.info("Edited design differs from the original." if changed else "No changes yet: edited = original.")

    config_json = json.dumps(config, sort_keys=True)
    h1, h2 = st.columns(2)
    with h1:
        show_png(cached_png("heatmap", output="ac_power", title="Original — AC power map"))
    with h2:
        show_png(cached_png("heatmap", output="ac_power", config_json=config_json, title="Edited — AC power map"))
    if st.toggle("Show the edited membership functions"):
        show_png(cached_png("all_membership", temp, hum, config_json=config_json))

    st.subheader(f"Scenario {scenario.key}: original vs edited vs ON/OFF")
    edit_results = cached_run_custom_fis(config_json, scenario, noise, occupancy)
    show_png(edit_sim_png(config_json, scenario, noise, occupancy))
    st.dataframe(sim.metrics_rows(edit_results, tariff=tariff, currency=currency), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Tab 5 — Reports & downloads
# ---------------------------------------------------------------------------
with tab_dl:
    st.subheader("PDF report for the current settings")
    st.caption("Summary, metrics table, the simulation graph, control surfaces and membership functions "
               "for the scenario and options chosen in the sidebar.")
    if st.button("Build PDF report"):
        with st.spinner("Building PDF…"):
            surf = default_surface()
            sections = [
                ("text", "Settings and headline results", [
                    f"Scenario {scenario.key}: {scenario.name} — start {scenario.T_start:g} °C / "
                    f"{scenario.H_start:g} %, outside {scenario.T_outside:g} °C / {scenario.H_outside:g} %"
                    + (f" (±{scenario.T_amp:g} °C daily swing)" if scenario.is_daily else "")
                    + f", {scenario.duration} min.",
                    f"Sensor noise: {'on' if noise else 'off'}. Occupancy eco mode: {'on' if occupancy else 'off'}. "
                    f"Tariff {currency}{tariff:g} per kWh.",
                    *[f"- {r.controller}: {r.metrics['kwh']:.2f} kWh ({currency}{r.metrics['kwh'] * tariff:.2f}), "
                      f"{r.metrics['switching_events']} switching events, "
                      f"{r.metrics['comfort_occupied_pct']:.0f} % of occupied time in comfort, final "
                      f"{r.metrics['final_T_C']:.2f} °C." for r in results],
                ]),
                ("table", "Metrics", [{k: v for k, v in r.items() if k != "Discomfort (°C·min)"} for r in rows]),
                ("figure", "Temperature and AC power over time", viz.plot_simulation(results)),
                ("figure", "Control surface — AC power", viz.plot_control_surface("ac_power", surf)),
                ("figure", "Control surface — fan speed", viz.plot_control_surface("fan_speed", surf)),
                ("figure", "Membership functions", viz.plot_all_membership(temp, hum)),
                ("figure", "Fuzzy PI control surface", viz.plot_pi_surface()),
            ]
            st.session_state["pdf_bytes"] = report_pdf.build_pdf(sections)
    if "pdf_bytes" in st.session_state:
        st.download_button("Download PDF report", st.session_state["pdf_bytes"],
                           file_name=f"fuzzy_report_{scenario.key}.pdf", mime="application/pdf")

    full = os.path.join(HERE, "outputs", "report.pdf")
    if os.path.exists(full):
        with open(full, "rb") as fh:
            st.download_button("Download full project report (all scenarios, from main.py)", fh.read(),
                               file_name="fuzzy_full_report.pdf", mime="application/pdf")
    else:
        st.caption("Run `python main.py` once to also offer the full multi-scenario PDF here.")

    st.subheader("Data")
    st.download_button("Download metrics (CSV)", pd.DataFrame(rows).to_csv(index=False).encode("utf-8"),
                       file_name=f"metrics_{scenario.key}.csv", mime="text/csv")
    ts = pd.DataFrame({"minute": results[0].time[:-1],
                       "T_out": results[0].T_out, "H_out": results[0].H_out,
                       "occupied": results[0].occupied,
                       **{f"T [{r.controller}]": r.T[:-1] for r in results},
                       **{f"ac [{r.controller}]": r.ac for r in results}})
    st.download_button("Download time series (CSV)", ts.to_csv(index=False).encode("utf-8"),
                       file_name=f"timeseries_{scenario.key}.csv", mime="text/csv")

    st.subheader("Hardware")
    cfg = st.session_state.get("edited_config", fc.DEFAULT_FIS.as_config())
    is_edited = json.dumps(cfg, sort_keys=True) != json.dumps(fc.DEFAULT_FIS.as_config(), sort_keys=True)
    st.caption("ESP32 lookup table for the " + ("**edited** design from the Editor tab." if is_edited
               else "original design (edit it in the Editor tab to export a different one)."))
    if st.button("Generate fuzzy_lut.h"):
        lut_fis = fis_from_config(cfg)
        ac_tab, fan_tab = export_lut.build_tables(lut_fis)
        tmp = os.path.join(HERE, "outputs", "fuzzy_lut_download.h")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        export_lut.write_header(ac_tab, fan_tab, tmp)
        with open(tmp, encoding="utf-8") as fh:
            st.session_state["lut_text"] = fh.read()
    if "lut_text" in st.session_state:
        st.download_button("Download fuzzy_lut.h", st.session_state["lut_text"], file_name="fuzzy_lut.h",
                           mime="text/x-c")
    st.download_button("Download FIS design (JSON)", json.dumps(cfg, indent=2), file_name="fis_design.json",
                       mime="application/json")
