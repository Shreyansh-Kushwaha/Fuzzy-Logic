"""
fuzzy_controller.py
===================

Mamdani Fuzzy Inference System (FIS) for automatic room temperature regulation.

Inputs
------
    temperature  (deg C)  universe [10, 40]
    humidity     (%RH)    universe [20, 90]

Outputs
-------
    ac_power     (%)      universe [-100, +100]   negative = heating, positive = cooling
    fan_speed    (%)      universe [0, 100]

Mamdani settings (stated explicitly, as used by `MamdaniFIS` below)
-------------------------------------------------------------------
    AND operator    : minimum      mu_A AND mu_B         = min(mu_A, mu_B)
    Implication     : minimum      clipped consequent    = min(w_i, mu_C(y))
    Aggregation     : maximum      mu_agg(y)             = max_i clipped_i(y)
    Defuzzification : centroid     y* = integral(y mu_agg(y)) / integral(mu_agg(y))

Structure of this module
------------------------
    MamdaniFIS   generic n-input / m-output Mamdani engine built on scikit-fuzzy
                 primitives (trimf, trapmf, interp_membership, defuzz). Also
                 used by fuzzy_pi.py for the improved controller.
    RoomFIS      the temperature/humidity -> ac_power/fan_speed system. Its
                 membership functions and rule consequents can be changed
                 (used by the dashboard's rule & MF editor).
    DEFAULT_FIS  RoomFIS with exactly the specified MFs and 9 rules.

Public API (unchanged, uses DEFAULT_FIS)
----------------------------------------
    compute(temp, hum)       -> (ac_power, fan_speed, rule_strengths)
    infer(temp, hum)         -> InferenceResult (all intermediate values)
    compute_many(temps, hums)-> (ac array, fan array)   vectorised, for grids
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import skfuzzy as fuzz

STEP = 0.1  # resolution of every universe of discourse

# ---------------------------------------------------------------------------
# 1. Default membership function definitions: name -> (type, parameters)
# ---------------------------------------------------------------------------
TEMP_RANGE = (10.0, 40.0)
HUM_RANGE = (20.0, 90.0)
AC_RANGE = (-100.0, 100.0)
FAN_RANGE = (0.0, 100.0)

TEMP_MF_DEFS = {
    "cold":        ("trapmf", [10, 10, 16, 22]),
    "comfortable": ("trimf",  [18, 23, 28]),
    "hot":         ("trapmf", [24, 30, 40, 40]),
}
HUM_MF_DEFS = {
    "low":    ("trapmf", [20, 20, 30, 45]),
    "medium": ("trimf",  [35, 50, 65]),
    "high":   ("trapmf", [55, 70, 90, 90]),
}
AC_MF_DEFS = {
    "strong_heat": ("trapmf", [-100, -100, -70, -40]),
    "mild_heat":   ("trimf",  [-60, -30, 0]),
    "off":         ("trimf",  [-15, 0, 15]),
    "mild_cool":   ("trimf",  [0, 30, 60]),
    "strong_cool": ("trapmf", [40, 70, 100, 100]),
}
FAN_MF_DEFS = {
    "low":    ("trapmf", [0, 0, 20, 40]),
    "medium": ("trimf",  [30, 50, 70]),
    "high":   ("trapmf", [60, 80, 100, 100]),
}

# ---------------------------------------------------------------------------
# 2. Default rule base: exactly 9 rules, antecedents joined with AND
#    (rule_no, temperature term, humidity term, ac_power term, fan_speed term)
# ---------------------------------------------------------------------------
RULES = [
    (1, "cold",        "low",    "strong_heat", "low"),
    (2, "cold",        "medium", "strong_heat", "low"),
    (3, "cold",        "high",   "mild_heat",   "medium"),
    (4, "comfortable", "low",    "off",         "low"),
    (5, "comfortable", "medium", "off",         "low"),
    (6, "comfortable", "high",   "mild_cool",   "medium"),
    (7, "hot",         "low",    "mild_cool",   "medium"),
    (8, "hot",         "medium", "strong_cool", "high"),
    (9, "hot",         "high",   "strong_cool", "high"),
]


def rule_text(rule: tuple) -> str:
    """Human-readable form of a room-FIS rule tuple."""
    no, t, h, a, f = rule
    return f"R{no}: IF temp is {t} AND humidity is {h} THEN ac is {a}, fan is {f}"


# ---------------------------------------------------------------------------
# 3. Building blocks
# ---------------------------------------------------------------------------
MF_PARAM_COUNT = {"trimf": 3, "trapmf": 4}


def make_universe(lo: float, hi: float, step: float = STEP) -> np.ndarray:
    """Universe of discourse; linspace so both end points are hit exactly."""
    n = int(round((hi - lo) / step)) + 1
    return np.linspace(lo, hi, n)


def build_mfs(universe: np.ndarray, defs: dict) -> dict[str, np.ndarray]:
    """Evaluate every membership function over its universe."""
    builders = {"trimf": fuzz.trimf, "trapmf": fuzz.trapmf}
    return {name: builders[kind](universe, list(params)) for name, (kind, params) in defs.items()}


def validate_mf_defs(defs: dict, lo: float, hi: float) -> list[str]:
    """
    Check user-edited MF definitions. Returns a list of problems (empty = valid).
    Parameters must be non-decreasing, inside the universe, and every set
    must have a non-zero width.
    """
    problems = []
    for name, (kind, params) in defs.items():
        if kind not in MF_PARAM_COUNT:
            problems.append(f"{name}: unknown MF type '{kind}'")
            continue
        if len(params) != MF_PARAM_COUNT[kind]:
            problems.append(f"{name}: {kind} needs {MF_PARAM_COUNT[kind]} parameters")
            continue
        p = [float(v) for v in params]
        if any(not math.isfinite(v) for v in p):
            problems.append(f"{name}: parameters must be finite numbers")
        elif any(b < a for a, b in zip(p, p[1:])):
            problems.append(f"{name}: parameters must be in non-decreasing order {p}")
        elif p[0] < lo or p[-1] > hi:
            problems.append(f"{name}: parameters must lie within [{lo:g}, {hi:g}]")
        elif p[-1] - p[0] <= 0:
            problems.append(f"{name}: set has zero width")
    return problems


def sanitize(value, lo: float, hi: float) -> float:
    """
    Convert `value` to a float inside [lo, hi].

    * Values outside the universe are clamped to the nearest edge
      (e.g. 45 °C -> 40 °C, which is still fully 'hot').
    * +/- infinity is clamped the same way.
    * NaN, None or non-numeric input falls back to the universe midpoint, so
      a faulty sensor reading cannot crash the controller.
    """
    try:
        x = float(value)
    except (TypeError, ValueError):
        return (lo + hi) / 2.0
    if math.isnan(x):
        return (lo + hi) / 2.0
    return float(min(max(x, lo), hi))


def sanitize_array(values, lo: float, hi: float) -> np.ndarray:
    """Vectorised `sanitize` for numeric arrays."""
    x = np.asarray(values, dtype=float)
    x = np.where(np.isnan(x), (lo + hi) / 2.0, x)
    return np.clip(x, lo, hi)


def fuzzify(x: float, universe: np.ndarray, mfs: dict[str, np.ndarray]) -> dict[str, float]:
    """Degree of membership of crisp x in every fuzzy set of a variable."""
    return {name: float(fuzz.interp_membership(universe, mf, x)) for name, mf in mfs.items()}


def centroid(universe: np.ndarray, aggregated: np.ndarray, default: float) -> float:
    """
    Centroid defuzzification with scikit-fuzzy. If the aggregated set is empty
    (no rule fired) skfuzzy would raise, so a safe default is returned instead.
    """
    if not np.any(aggregated > 0):
        return default
    return float(fuzz.defuzz(universe, aggregated, "centroid"))


def centroid_many(universe: np.ndarray, aggregated: np.ndarray, default: float) -> np.ndarray:
    """
    Vectorised exact centroid of piecewise-linear sets (one per row).

    Each segment [x1, x2] with heights y1, y2 is a trapezoid:
        area   = h (y1 + y2) / 2
        moment = x1 * area + h^2 (y1 + 2 y2) / 6
    This is the same geometry skfuzzy's centroid uses, so results agree to
    floating-point precision (checked in tests/test_fuzzy_controller.py).
    """
    x1 = universe[:-1]
    h = np.diff(universe)
    y1 = aggregated[:, :-1]
    y2 = aggregated[:, 1:]
    area = h * (y1 + y2) / 2.0
    moment = x1 * area + h ** 2 * (y1 + 2.0 * y2) / 6.0
    total = area.sum(axis=1)
    out = np.full(aggregated.shape[0], float(default))
    ok = total > 0
    out[ok] = moment[ok].sum(axis=1) / total[ok]
    return out


@dataclass
class Variable:
    """A linguistic variable: universe, MF definitions and evaluated MFs."""
    name: str
    label: str
    lo: float
    hi: float
    defs: dict
    universe: np.ndarray = field(init=False)
    mfs: dict = field(init=False)

    def __post_init__(self):
        self.defs = {k: (kind, list(p)) for k, (kind, p) in self.defs.items()}
        self.universe = make_universe(self.lo, self.hi)
        self.mfs = build_mfs(self.universe, self.defs)

    def as_dict(self) -> dict:
        """Shape used by the plotting code."""
        return {"label": self.label, "universe": self.universe, "mfs": self.mfs, "defs": self.defs}


# ---------------------------------------------------------------------------
# 4. Generic Mamdani engine
# ---------------------------------------------------------------------------
@dataclass
class FISResult:
    inputs: dict[str, float]                 # sanitised crisp inputs
    degrees: dict[str, dict[str, float]]     # fuzzification per input variable
    strengths: np.ndarray                    # firing strength of every rule
    clipped: dict[str, list[np.ndarray]]     # per output: per-rule clipped sets
    aggregated: dict[str, np.ndarray]        # per output: max-aggregated set
    crisp: dict[str, float]                  # per output: centroid value


class MamdaniFIS:
    """
    Generic Mamdani system.

    rules: list of (antecedents, consequents) where
        antecedents = {input_name: term, ...}   joined with AND (= min)
        consequents = {output_name: term, ...}
    defaults: crisp value per output when no rule fires.
    """

    def __init__(self, inputs: list[Variable], outputs: list[Variable],
                 rules: list[tuple[dict, dict]], defaults: dict[str, float] | None = None):
        self.inputs = {v.name: v for v in inputs}
        self.outputs = {v.name: v for v in outputs}
        self.rules = rules
        self.defaults = defaults or {name: 0.0 for name in self.outputs}
        for ants, cons in rules:
            for var, term in ants.items():
                if term not in self.inputs[var].mfs:
                    raise ValueError(f"unknown term '{term}' for input '{var}'")
            for var, term in cons.items():
                if term not in self.outputs[var].mfs:
                    raise ValueError(f"unknown term '{term}' for output '{var}'")

    # --- single evaluation, every intermediate kept --------------------------
    def infer(self, **crisp_inputs) -> FISResult:
        x = {n: sanitize(crisp_inputs.get(n), v.lo, v.hi) for n, v in self.inputs.items()}

        # Step 1 - Fuzzification
        degrees = {n: fuzzify(x[n], v.universe, v.mfs) for n, v in self.inputs.items()}

        strengths = np.zeros(len(self.rules))
        clipped = {n: [] for n in self.outputs}
        for i, (ants, cons) in enumerate(self.rules):
            # Step 2 - Rule evaluation, AND = min
            w = min(degrees[var][term] for var, term in ants.items())
            strengths[i] = w
            # Step 3 - Implication, min (clip each consequent at height w)
            for out_name, out_var in self.outputs.items():
                term = cons.get(out_name)
                mf = out_var.mfs[term] if term is not None else np.zeros_like(out_var.universe)
                clipped[out_name].append(np.fmin(w, mf))

        # Step 4 - Aggregation, max over all rules
        aggregated = {n: np.max(np.vstack(c), axis=0) for n, c in clipped.items()}

        # Step 5 - Defuzzification, centroid
        crisp = {}
        for n, v in self.outputs.items():
            value = centroid(v.universe, aggregated[n], self.defaults[n])
            crisp[n] = 0.0 if abs(value) < 1e-9 else value  # snap -1e-15 style noise
        return FISResult(x, degrees, strengths, clipped, aggregated, crisp)

    # --- vectorised evaluation for grids and the dashboard -------------------
    def compute_many(self, chunk: int = 512, **arrays) -> dict[str, np.ndarray]:
        """Evaluate many input points at once (same maths as `infer`)."""
        names = list(self.inputs)
        flat = {n: sanitize_array(arrays[n], self.inputs[n].lo, self.inputs[n].hi).ravel() for n in names}
        shape = np.shape(arrays[names[0]])
        n_pts = flat[names[0]].size
        out = {n: np.empty(n_pts) for n in self.outputs}
        for s in range(0, n_pts, chunk):
            sl = slice(s, s + chunk)
            deg = {n: {t: np.interp(flat[n][sl], v.universe, mf) for t, mf in v.mfs.items()}
                   for n, v in self.inputs.items()}
            w = [np.min(np.vstack([deg[var][term] for var, term in ants.items()]), axis=0)
                 for ants, _ in self.rules]
            for o_name, o_var in self.outputs.items():
                agg = np.zeros((w[0].size, o_var.universe.size))
                for (ants, cons), wi in zip(self.rules, w):
                    term = cons.get(o_name)
                    if term is not None:
                        np.maximum(agg, np.fmin(wi[:, None], o_var.mfs[term][None, :]), out=agg)
                out[o_name][sl] = centroid_many(o_var.universe, agg, self.defaults[o_name])
        for n in out:
            out[n][np.abs(out[n]) < 1e-9] = 0.0
            out[n] = out[n].reshape(shape)
        return out


# ---------------------------------------------------------------------------
# 5. The room controller FIS
# ---------------------------------------------------------------------------
@dataclass
class InferenceResult:
    temperature: float                 # clamped crisp input
    humidity: float                    # clamped crisp input
    temp_degrees: dict[str, float]     # fuzzification of temperature
    hum_degrees: dict[str, float]      # fuzzification of humidity
    rule_strengths: np.ndarray         # firing strength w_i of rules 1..9
    ac_clipped: list[np.ndarray]       # per-rule implied (clipped) ac_power sets
    fan_clipped: list[np.ndarray]      # per-rule implied (clipped) fan_speed sets
    ac_aggregated: np.ndarray          # max-aggregated ac_power set
    fan_aggregated: np.ndarray         # max-aggregated fan_speed set
    ac_power: float                    # crisp output (centroid)
    fan_speed: float                   # crisp output (centroid)


class RoomFIS:
    """Temperature + humidity -> ac_power + fan_speed. Every part is editable."""

    def __init__(self, temp_defs=None, hum_defs=None, ac_defs=None, fan_defs=None, rules=None):
        self.temperature = Variable("temperature", "Temperature (°C)", *TEMP_RANGE, temp_defs or TEMP_MF_DEFS)
        self.humidity = Variable("humidity", "Humidity (%RH)", *HUM_RANGE, hum_defs or HUM_MF_DEFS)
        self.ac_power = Variable("ac_power", "AC power (%)  [− heat | + cool]", *AC_RANGE, ac_defs or AC_MF_DEFS)
        self.fan_speed = Variable("fan_speed", "Fan speed (%)", *FAN_RANGE, fan_defs or FAN_MF_DEFS)
        self.rules = [tuple(r) for r in (rules or RULES)]
        generic_rules = [({"temperature": t, "humidity": h}, {"ac_power": a, "fan_speed": f})
                         for _, t, h, a, f in self.rules]
        # Defaults if nothing fires: AC off, fan at its minimum.
        self.engine = MamdaniFIS([self.temperature, self.humidity], [self.ac_power, self.fan_speed],
                                 generic_rules, defaults={"ac_power": 0.0, "fan_speed": 0.0})
        self.variables = {v.name: v.as_dict() for v in
                          (self.temperature, self.humidity, self.ac_power, self.fan_speed)}

    def infer(self, temp, hum) -> InferenceResult:
        r = self.engine.infer(temperature=temp, humidity=hum)
        return InferenceResult(
            temperature=r.inputs["temperature"], humidity=r.inputs["humidity"],
            temp_degrees=r.degrees["temperature"], hum_degrees=r.degrees["humidity"],
            rule_strengths=r.strengths,
            ac_clipped=r.clipped["ac_power"], fan_clipped=r.clipped["fan_speed"],
            ac_aggregated=r.aggregated["ac_power"], fan_aggregated=r.aggregated["fan_speed"],
            ac_power=r.crisp["ac_power"], fan_speed=r.crisp["fan_speed"],
        )

    def compute(self, temp, hum) -> tuple[float, float, np.ndarray]:
        r = self.infer(temp, hum)
        return r.ac_power, r.fan_speed, r.rule_strengths

    def compute_many(self, temps, hums) -> tuple[np.ndarray, np.ndarray]:
        out = self.engine.compute_many(temperature=temps, humidity=hums)
        return out["ac_power"], out["fan_speed"]

    def as_config(self) -> dict:
        """Plain-data description (MF defs + rules) for saving or editing."""
        return {"temperature": self.temperature.defs, "humidity": self.humidity.defs,
                "ac_power": self.ac_power.defs, "fan_speed": self.fan_speed.defs,
                "rules": [list(r) for r in self.rules]}


DEFAULT_FIS = RoomFIS()

# Module-level names kept for the rest of the project and for readability.
temp_universe = DEFAULT_FIS.temperature.universe
hum_universe = DEFAULT_FIS.humidity.universe
ac_universe = DEFAULT_FIS.ac_power.universe
fan_universe = DEFAULT_FIS.fan_speed.universe
temp_mfs = DEFAULT_FIS.temperature.mfs
hum_mfs = DEFAULT_FIS.humidity.mfs
ac_mfs = DEFAULT_FIS.ac_power.mfs
fan_mfs = DEFAULT_FIS.fan_speed.mfs
VARIABLES = DEFAULT_FIS.variables


def infer(temp, hum) -> InferenceResult:
    """Run the full Mamdani inference (default FIS) and return every intermediate."""
    return DEFAULT_FIS.infer(temp, hum)


def compute(temp, hum) -> tuple[float, float, np.ndarray]:
    """
    Crisp controller interface (default FIS).

    Returns
    -------
    ac_power : float        in [-100, 100]; negative = heating, positive = cooling
    fan_speed : float       in [0, 100]
    rule_strengths : array  firing strength of rules 1..9 (index 0 = rule 1)
    """
    return DEFAULT_FIS.compute(temp, hum)


def compute_many(temps, hums) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised compute for arrays of inputs (default FIS)."""
    return DEFAULT_FIS.compute_many(temps, hums)


# ---------------------------------------------------------------------------
# 6. Helpers
# ---------------------------------------------------------------------------
MODE_THRESHOLD = 5.0  # |ac_power| below this (%) is treated as "Idle"


def mode_label(ac_power: float) -> str:
    """Operating mode implied by the AC power command."""
    if ac_power <= -MODE_THRESHOLD:
        return "Heating"
    if ac_power >= MODE_THRESHOLD:
        return "Cooling"
    return "Idle"


def build_skfuzzy_ctrl(fis: RoomFIS | None = None):
    """
    Build the same FIS with the high-level `skfuzzy.control` API.

    skfuzzy.control defaults are AND = min, implication = min, aggregation = max
    and centroid defuzzification, i.e. the same Mamdani settings as `infer()`.
    Used only for cross-validation in main.py and the tests.
    """
    from skfuzzy import control as ctrl

    fis = fis or DEFAULT_FIS
    temperature = ctrl.Antecedent(fis.temperature.universe, "temperature")
    humidity = ctrl.Antecedent(fis.humidity.universe, "humidity")
    ac_power = ctrl.Consequent(fis.ac_power.universe, "ac_power", defuzzify_method="centroid")
    fan_speed = ctrl.Consequent(fis.fan_speed.universe, "fan_speed", defuzzify_method="centroid")
    for var, mfs in ((temperature, fis.temperature.mfs), (humidity, fis.humidity.mfs),
                     (ac_power, fis.ac_power.mfs), (fan_speed, fis.fan_speed.mfs)):
        for name, mf in mfs.items():
            var[name] = mf

    rules = [ctrl.Rule(temperature[t] & humidity[h], (ac_power[a], fan_speed[f]))
             for _, t, h, a, f in fis.rules]
    return ctrl.ControlSystemSimulation(ctrl.ControlSystem(rules))


if __name__ == "__main__":
    for t, h in [(32, 75), (14, 40), (23, 50), (100, -5), (float("nan"), None)]:
        ac, fan, w = compute(t, h)
        print(f"T={t!s:>5}  H={h!s:>5}  ->  ac={ac:7.2f} %  fan={fan:6.2f} %  "
              f"mode={mode_label(ac):8s} strengths={np.round(w, 3)}")
