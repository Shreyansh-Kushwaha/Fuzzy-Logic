"""
simulation.py
=============

First-order room thermal/humidity model, the controllers (fuzzy Mamdani,
fuzzy PI, ON/OFF), the experiment options (24-hour weather, occupancy eco
mode, sensor noise) and the performance metrics, including kWh and cost.

Room model (1-minute time step)
-------------------------------
    T[k+1] = T[k] + k1 * (T_out[k] - T[k]) - k2 * (ac[k] / 100)
    H[k+1] = H[k] - k3 * (ac[k] / 100 if ac[k] > 0 else 0) + k4 * (H_out[k] - H[k])
    H is clamped to [20, 90] %RH.

    k1 = 0.02  heat leakage coefficient (1/min)
    k2 = 0.5   max temperature change per minute produced by the AC (°C/min)
    k3 = 0.3   max dehumidification per minute while cooling (%RH/min)
    k4 = 0.01  small humidity drift toward the outdoor value (1/min)

Sign convention: ac > 0 is cooling (lowers T, removes moisture),
ac < 0 is heating (raises T, no effect on moisture).

Weather
-------
Scenarios A-C keep the outdoor conditions constant. Scenario D is a 24-hour
day: outdoor temperature follows a cosine with its peak at 15:00 and its
minimum at 03:00; outdoor humidity moves the opposite way (most humid at dawn).

Occupancy (eco dead band)
-------------------------
A scenario may define occupied hours. With occupancy control enabled, while
the room is empty the comfort band is widened to 20-27 °C, as a dual-setpoint
smart thermostat does:
    * inside 20-27 °C the AC is off (and the controller is reset);
    * once the room drifts more than 0.5 °C beyond an edge, the controller
      takes over and regulates the room back to that edge (cooling only
      above the band, heating only below it). It does so by
      seeing the temperature shifted by 3.5 °C, so the edge looks like the
      normal 23.5 °C setpoint (27 - 3.5 = 23.5, 20 + 3.5 = 23.5). All three
      controllers get exactly the same treatment;
    * it hands back to "off" once the room is 0.5 °C inside the band again
      (hysteresis, so the AC cannot flicker at the edge).
Normal control returns 30 minutes before people arrive (pre-conditioning),
so the room is comfortable when they walk in.

Sensor noise
------------
Optional Gaussian measurement noise (σ = 0.2 °C, 2 %RH, the DHT22
datasheet repeatability) is added to what the controller *sees*; the room
itself is unaffected. A fixed seed keeps runs
reproducible, and every controller sees exactly the same noise sequence.

Energy
------
Abstract energy  = Σ |ac| (% x minutes), as in the original specification.
Electrical energy (kWh) assumes a 1.5-ton inverter split AC drawing 1.5 kW
of electricity at 100 % (heating or cooling, heat-pump mode) plus a 60 W fan:
    kWh = Σ (|ac|/100 * 1.5 + fan/100 * 0.06) / 60
Cost = kWh x tariff (default ₹8 per kWh; editable in the dashboard).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

import fuzzy_controller as fc
from fuzzy_pi import FuzzyPIController

# ---------------------------------------------------------------------------
# Model and experiment constants
# ---------------------------------------------------------------------------
K1 = 0.02           # heat leakage
K2 = 0.5            # max °C change per minute from the AC at 100 %
K3 = 0.3            # max %RH removed per minute when cooling at 100 %
K4 = 0.01           # humidity drift toward outside
H_MIN, H_MAX = 20.0, 90.0

DURATION_MIN = 120
COMFORT_LOW, COMFORT_HIGH = 22.0, 25.0
SETPOINT = 23.5
HYSTERESIS = 1.0
SSE_WINDOW = 30     # minutes used for steady-state error

ECO_LOW, ECO_HIGH = 20.0, 27.0          # widened band while the room is empty
ECO_HYSTERESIS = 0.5                    # °C beyond/inside an edge to start/stop control
ECO_SETBACK = SETPOINT - ECO_LOW        # 3.5 °C shift that maps an eco edge onto the setpoint
PRECONDITION_MIN = 30                   # resume normal control this long before arrival
NOISE_STD_T, NOISE_STD_H = 0.2, 2.0     # sensor noise (°C, %RH), DHT22 repeatability
NOISE_SEED = 42

AC_ELEC_KW = 1.5    # electrical draw of the AC at 100 %
FAN_ELEC_KW = 0.06  # electrical draw of the indoor fan at 100 %
TARIFF = 8.0        # price per kWh
CURRENCY = "₹"


@dataclass(frozen=True)
class Scenario:
    key: str
    name: str
    T_start: float
    H_start: float
    T_outside: float            # constant value, or daily mean when T_amp > 0
    H_outside: float            # constant value, or daily mean when H_amp > 0
    duration: int = DURATION_MIN
    T_amp: float = 0.0          # daily swing of outdoor temperature (± °C)
    H_amp: float = 0.0          # daily swing of outdoor humidity (± %RH)
    start_minute: int = 0       # clock time at t = 0 (minutes after midnight)
    occupied: tuple[int, int] | None = None   # occupied clock minutes [start, end)

    @property
    def is_daily(self) -> bool:
        return self.T_amp != 0 or self.H_amp != 0


SCENARIOS = {
    "A": Scenario("A", "Hot humid day", T_start=34, H_start=75, T_outside=36, H_outside=80),
    "B": Scenario("B", "Cold day",      T_start=14, H_start=40, T_outside=10, H_outside=40),
    "C": Scenario("C", "Mild day",      T_start=26, H_start=60, T_outside=27, H_outside=60),
    "D": Scenario("D", "24-hour summer day (office)", T_start=28, H_start=65,
                  T_outside=30, H_outside=65, duration=24 * 60, T_amp=6, H_amp=15,
                  start_minute=0, occupied=(9 * 60, 18 * 60)),
}


def outside_conditions(sc: Scenario, k: int) -> tuple[float, float]:
    """Outdoor temperature and humidity at minute k of the scenario."""
    if not sc.is_daily:
        return float(sc.T_outside), float(sc.H_outside)
    hour = ((sc.start_minute + k) % 1440) / 60.0
    phase = math.cos(2 * math.pi * (hour - 15.0) / 24.0)     # +1 at 15:00, -1 at 03:00
    T_out = sc.T_outside + sc.T_amp * phase
    H_out = min(max(sc.H_outside - sc.H_amp * phase, H_MIN), H_MAX)
    return T_out, H_out


def is_occupied(sc: Scenario, k: int, lead: int = 0) -> bool:
    """
    True when people are in the room at minute k (always, if no schedule).
    `lead` starts the occupied period that many minutes early (pre-conditioning).
    """
    if sc.occupied is None:
        return True
    minute_of_day = (sc.start_minute + k) % 1440
    return sc.occupied[0] - lead <= minute_of_day < sc.occupied[1]


# ---------------------------------------------------------------------------
# Plant
# ---------------------------------------------------------------------------
def room_step(T: float, H: float, ac_power: float, T_out: float, H_out: float) -> tuple[float, float]:
    """Advance the room state by one minute."""
    T_next = T + K1 * (T_out - T) - K2 * (ac_power / 100.0)
    dehumidify = K3 * (ac_power / 100.0) if ac_power > 0 else 0.0
    H_next = H - dehumidify + K4 * (H_out - H)
    H_next = min(max(H_next, H_MIN), H_MAX)
    return T_next, H_next


# ---------------------------------------------------------------------------
# Controllers: each maps the measured state to (ac_power, fan_speed)
# ---------------------------------------------------------------------------
class FuzzyController:
    """The 9-rule Mamdani FIS (or any edited RoomFIS)."""

    def __init__(self, fis: fc.RoomFIS | None = None, name: str = "Fuzzy (Mamdani)"):
        self.fis = fis or fc.DEFAULT_FIS
        self.name = name

    def reset(self) -> None:
        pass

    def __call__(self, T: float, H: float) -> tuple[float, float]:
        ac, fan = self.fis.compute_many(np.array([T]), np.array([H]))
        return float(ac[0]), float(fan[0])


class OnOffController:
    """
    Classic bang-bang thermostat, setpoint 23.5 °C, hysteresis ±1 °C.

        * Cooling (+100 %) switches ON when T > setpoint + 1 (24.5 °C)
          and stays on until T <= setpoint (23.5 °C).
        * Heating (-100 %) switches ON when T < setpoint - 1 (22.5 °C)
          and stays on until T >= setpoint (23.5 °C).
        * Otherwise the AC is off (0 %).

    Switching off at the setpoint (rather than at the opposite band edge)
    keeps the heating and cooling bands disjoint, so the thermostat can never
    jump straight from cooling to heating. Fan runs at 100 % whenever the AC runs.
    """

    name = "ON/OFF thermostat"

    def __init__(self, setpoint: float = SETPOINT, hysteresis: float = HYSTERESIS):
        self.setpoint = setpoint
        self.hysteresis = hysteresis
        self.state = 0  # -1 heating, 0 off, +1 cooling

    def reset(self) -> None:
        self.state = 0

    def __call__(self, T: float, H: float) -> tuple[float, float]:
        sp, hy = self.setpoint, self.hysteresis
        if self.state == 1 and T <= sp:
            self.state = 0
        elif self.state == -1 and T >= sp:
            self.state = 0
        if self.state == 0:
            if T > sp + hy:
                self.state = 1
            elif T < sp - hy:
                self.state = -1
        ac = 100.0 * self.state
        return ac, (100.0 if self.state != 0 else 0.0)


CONTROLLER_FACTORIES = {
    "mamdani": lambda: FuzzyController(),
    "pi": lambda: FuzzyPIController(),
    "onoff": lambda: OnOffController(),
}
CONTROLLER_LABELS = {"mamdani": "Fuzzy (Mamdani)", "pi": "Fuzzy PI", "onoff": "ON/OFF thermostat"}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
@dataclass
class SimResult:
    controller: str
    scenario: Scenario
    time: np.ndarray          # 0..duration (state sample times, minutes)
    T: np.ndarray             # duration + 1 samples (true room temperature)
    H: np.ndarray             # duration + 1 samples
    ac: np.ndarray            # duration actions, ac[k] applied during minute k
    fan: np.ndarray           # duration actions
    T_out: np.ndarray         # duration samples
    H_out: np.ndarray         # duration samples
    occupied: np.ndarray      # duration booleans (schedule; all True if none)
    eco: np.ndarray           # duration booleans: eco setback active
    T_measured: np.ndarray    # sensor reading (differs from T only with noise)
    noise: bool = False
    occupancy_control: bool = False
    metrics: dict = field(default_factory=dict)


def simulate(controller, scenario: Scenario, noise: bool = False, occupancy: bool = False,
             seed: int = NOISE_SEED) -> SimResult:
    """Run one controller on one scenario and compute its metrics."""
    controller.reset()
    n = scenario.duration
    T = np.empty(n + 1)
    H = np.empty(n + 1)
    ac = np.empty(n)
    fan = np.empty(n)
    T_out = np.empty(n)
    H_out = np.empty(n)
    occ = np.empty(n, dtype=bool)
    eco = np.zeros(n, dtype=bool)
    T_meas = np.empty(n)
    T[0], H[0] = scenario.T_start, scenario.H_start
    eco_dir = 0          # eco state: 0 idle, +1 cooling back to 27 °C, -1 heating back to 20 °C
    rng = np.random.default_rng(seed)
    noise_T = rng.normal(0.0, NOISE_STD_T, n) if noise else np.zeros(n)
    noise_H = rng.normal(0.0, NOISE_STD_H, n) if noise else np.zeros(n)

    for k in range(n):
        T_out[k], H_out[k] = outside_conditions(scenario, k)
        occ[k] = is_occupied(scenario, k)
        Tm, Hm = T[k] + noise_T[k], H[k] + noise_H[k]
        T_meas[k] = Tm
        if occupancy and not is_occupied(scenario, k, lead=PRECONDITION_MIN):
            eco[k] = True
            eco_dir = _eco_direction(Tm, eco_dir)
            if eco_dir == 0:                     # inside the wide band: AC off
                ac[k], fan[k] = 0.0, 0.0
                controller.reset()
            else:                                # drifted out: regulate back to the edge
                T_seen = Tm - ECO_SETBACK if eco_dir > 0 else Tm + ECO_SETBACK
                ac[k], fan[k] = controller(T_seen, Hm)
                # only push back toward the band: cool above it, heat below it
                ac[k] = max(ac[k], 0.0) if eco_dir > 0 else min(ac[k], 0.0)
        else:
            eco_dir = 0
            ac[k], fan[k] = controller(Tm, Hm)
        T[k + 1], H[k + 1] = room_step(T[k], H[k], ac[k], T_out[k], H_out[k])

    res = SimResult(controller.name, scenario, np.arange(n + 1), T, H, ac, fan,
                    T_out, H_out, occ, eco, T_meas, noise, occupancy)
    res.metrics = compute_metrics(res)
    return res


def _eco_direction(T: float, current: int) -> int:
    """Eco dead-band state machine with hysteresis (see module docstring)."""
    if current == 0:
        if T > ECO_HIGH + ECO_HYSTERESIS:
            return 1
        if T < ECO_LOW - ECO_HYSTERESIS:
            return -1
        return 0
    if current > 0 and T <= ECO_HIGH - ECO_HYSTERESIS:
        return 0
    if current < 0 and T >= ECO_LOW + ECO_HYSTERESIS:
        return 0
    return current


def run_scenario(scenario: Scenario, controllers=("mamdani", "pi", "onoff"),
                 noise: bool = False, occupancy: bool = False) -> list[SimResult]:
    """Run several controllers on the same scenario (same noise sequence)."""
    return [simulate(CONTROLLER_FACTORIES[c](), scenario, noise=noise, occupancy=occupancy)
            for c in controllers]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def settling_time(T: np.ndarray, lo: float = COMFORT_LOW, hi: float = COMFORT_HIGH):
    """
    First minute after which T enters the comfort band and never leaves it
    again for the rest of the run. Returns None if it never settles.
    """
    inside = (T >= lo) & (T <= hi)
    if not inside[-1]:
        return None
    outside_idx = np.where(~inside)[0]
    return 0 if outside_idx.size == 0 else int(outside_idx[-1] + 1)


def max_overshoot(T: np.ndarray, setpoint: float = SETPOINT) -> float:
    """
    Largest excursion past the setpoint on the side opposite to the start.
    Room starting warm (T0 > setpoint): overshoot = max(0, setpoint - min T).
    Room starting cool (T0 < setpoint): overshoot = max(0, max T - setpoint).
    """
    if T[0] >= setpoint:
        return float(max(0.0, setpoint - T.min()))
    return float(max(0.0, T.max() - setpoint))


def switching_events(ac: np.ndarray, threshold: float = fc.MODE_THRESHOLD) -> int:
    """
    Number of changes of operating mode (heating / idle / cooling).
    |ac| < threshold counts as idle; the AC is assumed idle before t = 0,
    so the first switch-on is counted.
    """
    modes = np.where(ac >= threshold, 1, np.where(ac <= -threshold, -1, 0))
    modes = np.concatenate(([0], modes))
    return int(np.count_nonzero(np.diff(modes)))


def electrical_kwh(ac: np.ndarray, fan: np.ndarray) -> float:
    """Electrical energy in kWh for 1-minute steps."""
    kw = np.abs(ac) / 100.0 * AC_ELEC_KW + fan / 100.0 * FAN_ELEC_KW
    return float(kw.sum() / 60.0)


def compute_metrics(res: SimResult) -> dict:
    T, ac = res.T, res.ac
    T_k = T[:-1]                               # temperature during each minute
    in_band = (T_k >= COMFORT_LOW) & (T_k <= COMFORT_HIGH)
    occ = res.occupied
    discomfort = np.maximum(0.0, np.maximum(COMFORT_LOW - T_k, T_k - COMFORT_HIGH))
    return {
        "settling_time_min": settling_time(T),
        "max_overshoot_C": max_overshoot(T),
        "steady_state_error_C": float(np.mean(np.abs(T[-SSE_WINDOW:] - SETPOINT))),
        "energy": float(np.sum(np.abs(ac))),   # % x minutes
        "kwh": electrical_kwh(ac, res.fan),
        "switching_events": switching_events(ac),
        "final_T_C": float(T[-1]),
        "final_H_pct": float(res.H[-1]),
        "time_in_comfort_pct": float(np.mean((T >= COMFORT_LOW) & (T <= COMFORT_HIGH)) * 100),
        "comfort_occupied_pct": float(in_band[occ].mean() * 100) if occ.any() else float("nan"),
        "discomfort_Cmin": float(discomfort[occ].sum()),   # °C·min outside band while occupied
    }


def energy_saving_pct(energy: float, baseline_energy: float) -> float:
    """Energy saved relative to the baseline (positive = saving)."""
    if baseline_energy == 0:
        return 0.0
    return (baseline_energy - energy) / baseline_energy * 100.0


def fmt_settling(value) -> str:
    return "not settled" if value is None else f"{value} min"


def metrics_rows(results: list[SimResult], tariff: float = TARIFF, currency: str = CURRENCY,
                 label: str | None = None) -> list[dict]:
    """
    Comparison table rows. Savings are relative to the ON/OFF thermostat when
    it is among the results: "Energy saving" uses Σ|ac| (the original
    specification), "kWh saving" the electrical model including the fan.
    String-valued columns stay strings in every row (one dtype per column).
    """
    base = next((r for r in results if r.controller == OnOffController.name), None)
    rows = []
    for r in results:
        m = r.metrics
        if base is None or r is base:
            saving = kwh_saving = "-"
        else:
            saving = f"{energy_saving_pct(m['energy'], base.metrics['energy']):.1f}"
            kwh_saving = f"{energy_saving_pct(m['kwh'], base.metrics['kwh']):.1f}"
        rows.append({
            "Scenario": label or f"{r.scenario.key}) {r.scenario.name}",
            "Controller": r.controller,
            "Settling time": fmt_settling(m["settling_time_min"]),
            "Max overshoot (°C)": round(m["max_overshoot_C"], 2),
            "SS error (°C)": round(m["steady_state_error_C"], 2),
            "Energy (%·min)": round(m["energy"], 1),
            "Energy (kWh)": round(m["kwh"], 3),
            f"Cost ({currency})": round(m["kwh"] * tariff, 2),
            "Switching events": m["switching_events"],
            "Comfort (% of occupied time)": round(m["comfort_occupied_pct"], 1),
            "Discomfort (°C·min)": round(m["discomfort_Cmin"], 1),
            "Final T (°C)": round(m["final_T_C"], 2),
            "Energy saving vs ON/OFF (%)": saving,       # Σ|ac| basis (original spec)
            "kWh saving vs ON/OFF (%)": kwh_saving,     # includes fan electricity
        })
    return rows


def custom_scenario(T_start: float, H_start: float, T_out: float, H_out: float,
                    duration: int = DURATION_MIN, daily: bool = False) -> Scenario:
    """Scenario from user values (daily=True adds the 24-h cosine swing)."""
    base = Scenario("Custom", "Custom", T_start, H_start, T_out, H_out, duration=duration)
    if daily:
        base = replace(base, duration=24 * 60, T_amp=6, H_amp=15, occupied=(9 * 60, 18 * 60))
    return base
