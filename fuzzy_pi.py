"""
fuzzy_pi.py
===========

Improved controller: an incremental ("velocity-form") Fuzzy PI controller.

Why
---
The 9-rule Mamdani FIS maps the *current* temperature straight to an AC
command, so it behaves like a proportional controller. Under a strong outdoor
load it settles where its output balances the heat leak, a little outside the
comfort zone (25.2 °C in scenario A, 20.7 °C in scenario B).

How
---
This controller looks at the error from the setpoint and how fast it changes,
and decides how much to *change* the AC command each minute:

    e[k]   = T[k] - T_sp(H[k])                 (°C, positive = too warm)
    de[k]  = e[k] - e[k-1]                     (°C per minute)
    du[k]  = FIS(e[k], de[k])                  (% per minute, Mamdani, centroid)
    u[k]   = clip(u[k-1] + du[k], -100, +100)  (the summation is the integral action)

At steady state e = 0 and de = 0, the rule base gives du = 0, and u stays at
whatever value balances the room's heat leak, so the offset disappears.
Clipping u to ±100 % is the anti-windup.

Humidity compensation: humid air feels warmer, so the setpoint is lowered by
up to 0.5 °C in proportion to how "high" the humidity is, using the same
humidity membership function as the main FIS:
    T_sp(H) = 23.5 - 0.5 * mu_high(H)

Measurement filter: the change of error is a difference of two readings, so
sensor noise is amplified (two readings with σ = 0.2 °C give Δe noise of
about 0.28 °C/min, as large as the Δe sets themselves). The controller
therefore smooths the temperature with a first-order low-pass filter
(exponential moving average, α = 0.5) before computing e and Δe:
    T_f[k] = α T[k] + (1 - α) T_f[k-1]

The fan speed still comes from the 9-rule room FIS (humidity-aware).

Mamdani settings are the same as the main FIS: AND = min, implication = min,
aggregation = max, defuzzification = centroid.
"""

from __future__ import annotations

import numpy as np

import fuzzy_controller as fc

SETPOINT = 23.5
FILTER_ALPHA = 0.5              # EMA weight of the newest temperature reading
HUMIDITY_SETPOINT_SHIFT = 0.5   # °C lower setpoint when humidity is fully "high"

# ---------------------------------------------------------------------------
# Linguistic variables
# ---------------------------------------------------------------------------
ERROR_DEFS = {                      # e = T - setpoint (°C)
    "NB": ("trapmf", [-6, -6, -3, -1.5]),
    "NS": ("trimf",  [-3, -1.5, 0]),
    "ZE": ("trimf",  [-1.5, 0, 1.5]),
    "PS": ("trimf",  [0, 1.5, 3]),
    "PB": ("trapmf", [1.5, 3, 6, 6]),
}
DERROR_DEFS = {                     # de = change of error per minute (°C/min)
    "N": ("trapmf", [-1, -1, -0.3, 0]),
    "Z": ("trimf",  [-0.3, 0, 0.3]),
    "P": ("trapmf", [0, 0.3, 1, 1]),
}
DU_DEFS = {                         # du = change of AC command (%/min)
    "NB": ("trapmf", [-20, -20, -15, -8]),
    "NS": ("trimf",  [-12, -6, 0]),
    "ZE": ("trimf",  [-3, 0, 3]),
    "PS": ("trimf",  [0, 6, 12]),
    "PB": ("trapmf", [8, 15, 20, 20]),
}

# Rule table (error rows x change-of-error columns) -> du.
# The table is antisymmetric (swap every sign and you get the same table), so
# heating and cooling behave alike. The ZE row brakes hard (NB/PB) when the
# room is already moving fast through the setpoint, which keeps overshoot small.
# Tuning record: the first version (ZE row NS/ZE/PS, PS-N -> ZE, NS-P -> ZE)
# overshot by 1.49 °C in scenario A; this table overshoots by 0.38 °C.
#             de: N      Z      P
PI_RULE_TABLE = {
    "NB": {"N": "NB", "Z": "NB", "P": "NS"},
    "NS": {"N": "NS", "Z": "NS", "P": "PS"},
    "ZE": {"N": "NB", "Z": "ZE", "P": "PB"},
    "PS": {"N": "NS", "Z": "PS", "P": "PS"},
    "PB": {"N": "PS", "Z": "PB", "P": "PB"},
}

error_var = fc.Variable("error", "Error e = T − setpoint (°C)", -6.0, 6.0, ERROR_DEFS)
derror_var = fc.Variable("d_error", "Change of error Δe (°C/min)", -1.0, 1.0, DERROR_DEFS)
du_var = fc.Variable("du", "Change of AC command Δu (%/min)", -20.0, 20.0, DU_DEFS)

PI_RULES = [({"error": e, "d_error": d}, {"du": out})
            for e, row in PI_RULE_TABLE.items() for d, out in row.items()]

PI_FIS = fc.MamdaniFIS([error_var, derror_var], [du_var], PI_RULES, defaults={"du": 0.0})
PI_VARIABLES = {v.name: v.as_dict() for v in (error_var, derror_var, du_var)}


def humidity_setpoint(hum: float) -> float:
    """Setpoint lowered by up to 0.5 °C when the air is humid."""
    h = fc.sanitize(hum, *fc.HUM_RANGE)
    mu_high = fc.fuzzify(h, fc.hum_universe, fc.hum_mfs)["high"]
    return SETPOINT - HUMIDITY_SETPOINT_SHIFT * mu_high


class FuzzyPIController:
    """Stateful incremental fuzzy PI controller (call once per minute)."""

    name = "Fuzzy PI"

    def __init__(self, room_fis: fc.RoomFIS | None = None):
        self.room_fis = room_fis or fc.DEFAULT_FIS
        self.reset()

    def reset(self) -> None:
        self.u = 0.0
        self.prev_error = None
        self.T_filtered = None

    def __call__(self, T: float, H: float) -> tuple[float, float]:
        T = fc.sanitize(T, -50.0, 80.0)
        # Low-pass filter the reading before the difference (see module docstring)
        if self.T_filtered is None:
            self.T_filtered = T
        else:
            self.T_filtered = FILTER_ALPHA * T + (1 - FILTER_ALPHA) * self.T_filtered
        e = self.T_filtered - humidity_setpoint(H)
        de = 0.0 if self.prev_error is None else e - self.prev_error
        self.prev_error = e
        # compute_many on one point = same maths as infer(), without keeping
        # the intermediate sets (about 10x faster inside long simulations)
        du = float(PI_FIS.compute_many(error=np.array([e]), d_error=np.array([de]))["du"][0])
        self.u = float(np.clip(self.u + du, -100.0, 100.0))
        _, fan = self.room_fis.compute_many(np.array([T]), np.array([H]))
        return self.u, float(fan[0])
