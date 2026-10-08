# Mamdani Fuzzy Logic Controller for Automatic Room Temperature Regulation using Temperature and Humidity Inputs

---

## Abstract

This project designs, implements and evaluates a two-input, two-output Mamdani
fuzzy logic controller (FLC) for indoor climate regulation. Room temperature and
relative humidity are fuzzified with three linguistic terms each. Nine IF–THEN rules
map them to a bipolar AC power command (−100 % = full heating, +100 % = full cooling)
and a fan speed. Inference uses min for AND, min implication, max aggregation and
centroid defuzzification. The controller is implemented in Python with
scikit-fuzzy. Its outputs were checked by hand on a worked example and against
scikit-fuzzy's own `control` module, with agreement to within 7 × 10⁻⁵ %. A
first-order thermal and humidity model of a room was simulated for 120 minutes in
three scenarios (hot–humid, cold and mild), and the FLC was compared with an ON/OFF
thermostat (23.5 °C ± 1 °C).

The FLC gave smooth, overshoot-free responses with a single mode switch per run,
against 10–20 switches for the thermostat. It used 14.0 % and 21.1 % less energy in
the hot and cold scenarios and 8.3 % more in the mild scenario. However, under large
indoor–outdoor temperature differences the FLC settled at 25.24 °C and 20.69 °C, just
outside the 22–25 °C comfort zone. Much of the energy saving therefore comes from a
steady-state offset, which is a known limitation of static, proportional-type fuzzy
controllers.

An incremental Fuzzy PI extension (error and change of error → change of command)
removes the offset, settling at 23.5 °C in the cold scenario, with a single switching
event. On a 24-hour office day it keeps 100 % of occupied time comfortable with 5
switching events, against 180 for the thermostat. An occupancy eco dead band saves a
further 24–37 % of electricity. The work is completed by electrical energy and cost
estimates, a sensor-noise study, an ESP32 + DHT22 lookup-table implementation, an
interactive dashboard with an animated room view and a rule editor, and 44 automated
tests.

---

## 1. Introduction

Heating, ventilation and air-conditioning (HVAC) accounts for a large share of
building energy use. Most residential units still use **ON/OFF (bang-bang)
thermostats**. These are cheap and robust, but they run the compressor at full power
in short cycles. The result is a saw-tooth temperature, frequent switching (compressor
wear, noise) and no use of secondary comfort variables such as humidity.

Fuzzy logic control suits this problem because human thermal comfort is
inherently vague. "Slightly warm and rather humid" cannot be captured well by a single
crisp threshold. A fuzzy controller encodes expert heuristics directly as linguistic
rules, needs no precise mathematical model of the room, and produces a **continuous**
control action. That continuous action can drive variable-speed (inverter)
compressors and fans.

**Objectives**

1. Design a Mamdani FIS with temperature and humidity inputs and AC power and fan
   speed outputs.
2. Visualise its membership functions, control surfaces and a worked inference
   example.
3. Simulate a room under three weather scenarios.
4. Compare the FLC with an ON/OFF thermostat on settling time, overshoot,
   steady-state error, energy and switching.
5. Provide an interactive dashboard for exploration and teaching.

---

## 2. Fuzzy Logic Theory

### 2.1 Fuzzy sets and fuzzification

A fuzzy set *A* on a universe *X* is defined by a membership function
μ_A : X → [0, 1]. This differs from a crisp set, where membership is either 0 or 1.
**Fuzzification** maps a crisp sensor reading x₀ to the degrees μ_A(x₀) of every
linguistic term of that variable. This project uses two shapes:

Triangular:

  trimf(x; a, b, c) = max( min( (x − a)/(b − a), (c − x)/(c − b) ), 0 )

Trapezoidal:

  trapmf(x; a, b, c, d) = max( min( (x − a)/(b − a), 1, (d − x)/(d − c) ), 0 )

(When a = b or c = d, the corresponding ramp is replaced by a vertical edge. This gives
the "shoulder" sets at the ends of each universe.)

### 2.2 Mamdani inference

For rule *i*: **IF** x is Aᵢ **AND** y is Bᵢ **THEN** z is Cᵢ

1. **Rule firing strength (AND = min)**

   wᵢ = min( μ_Aᵢ(x₀), μ_Bᵢ(y₀) )

2. **Implication (min)**: each consequent set is clipped at the firing strength

   μ′_Cᵢ(z) = min( wᵢ, μ_Cᵢ(z) )

3. **Aggregation (max)**: all clipped consequents are combined

   μ_agg(z) = maxᵢ μ′_Cᵢ(z)

The process runs independently for each output variable (ac_power and fan_speed).
Both outputs share the same firing strengths.

### 2.3 Centroid defuzzification

The aggregated fuzzy set is converted back to a crisp command by its centre of
gravity:

  z* = ∫ z · μ_agg(z) dz / ∫ μ_agg(z) dz

On the discretised universe {z₁, …, z_N} (step 0.1) this becomes

  z* ≈ Σₖ zₖ · μ_agg(zₖ) / Σₖ μ_agg(zₖ)

scikit-fuzzy evaluates the integral exactly for the piecewise-linear set.
The centroid is smooth with respect to the inputs and takes every active rule into
account. A consequence is that the output can never reach the extreme ends of the
universe: the largest achievable cooling command is the centroid of `strong_cool`
alone, 76.67 %, and the largest heating command is −76.67 %.

---

## 3. System Design

### 3.1 Block diagram (description)

```
             ┌──────────────────────────── Fuzzy Logic Controller ─────────────────────────────┐
 T (°C) ───► │ Clamp ─► Fuzzification ─► Rule base (9 rules, AND=min) ─► Implication (min)       │
 H (%)  ───► │ Clamp ─► Fuzzification ─┘                                ─► Aggregation (max)      │
             │                                                          ─► Centroid defuzzifier   │
             └───────────────────────────────────────┬───────────────────────────┬────────────────┘
                                                      │ ac_power (−100…+100 %)    │ fan_speed (0…100 %)
                                                      ▼                           ▼
                                          ┌────────────────────── Room (plant) ──────────────────┐
             T_out, H_out (disturbance) ─►│  T+ = T + k1(T_out − T) − k2·ac/100                   │
                                          │  H+ = H − k3·max(ac,0)/100 + k4(H_out − H)            │
                                          └─────────────────────┬────────────────────────────────┘
                                                                 │  T, H  (sensor feedback, 1-min sample)
                                                                 └──────────────► back to the FLC inputs
```

The temperature and humidity sensors feed the FLC once per minute. Each input is
first **clamped** to its universe, so out-of-range or faulty readings cannot crash
the controller. The FLC returns two crisp commands. The AC power command acts on the
room's temperature (and its humidity while cooling). The fan command is reported
but not used by the simplified thermal model. The outdoor temperature and humidity act
as constant disturbances.

### 3.2 Membership function table

| Variable | Universe | Term | Type | Parameters |
|---|---|---|---|---|
| temperature (°C) | [10, 40] | cold | trapmf | [10, 10, 16, 22] |
| | | comfortable | trimf | [18, 23, 28] |
| | | hot | trapmf | [24, 30, 40, 40] |
| humidity (%) | [20, 90] | low | trapmf | [20, 20, 30, 45] |
| | | medium | trimf | [35, 50, 65] |
| | | high | trapmf | [55, 70, 90, 90] |
| ac_power (%) | [−100, 100] | strong_heat | trapmf | [−100, −100, −70, −40] |
| | | mild_heat | trimf | [−60, −30, 0] |
| | | off | trimf | [−15, 0, 15] |
| | | mild_cool | trimf | [0, 30, 60] |
| | | strong_cool | trapmf | [40, 70, 100, 100] |
| fan_speed (%) | [0, 100] | low | trapmf | [0, 0, 20, 40] |
| | | medium | trimf | [30, 50, 70] |
| | | high | trapmf | [60, 80, 100, 100] |

Figures: `outputs/figures/mf_temperature.png`, `mf_humidity.png`, `mf_ac_power.png`,
`mf_fan_speed.png`.

### 3.3 Rule table

| # | Temperature | Humidity | → ac_power | → fan_speed |
|---|---|---|---|---|
| 1 | cold | low | strong_heat | low |
| 2 | cold | medium | strong_heat | low |
| 3 | cold | high | mild_heat | medium |
| 4 | comfortable | low | off | low |
| 5 | comfortable | medium | off | low |
| 6 | comfortable | high | mild_cool | medium |
| 7 | hot | low | mild_cool | medium |
| 8 | hot | medium | strong_cool | high |
| 9 | hot | high | strong_cool | high |

The rule base is complete: the input partitions cover both universes, so at least one
rule fires for every input pair. Humidity modulates the action in two ways. High
humidity in a comfortable room triggers mild cooling (dehumidification), and dry heat
needs only mild cooling.

### 3.4 Worked example (T = 32 °C, H = 75 %)

**Fuzzification**

| Variable | Term | Calculation | μ |
|---|---|---|---|
| temperature | cold | 32 > 22 | 0 |
| | comfortable | 32 > 28 | 0 |
| | hot | 30 ≤ 32 ≤ 40 (plateau) | **1** |
| humidity | low | 75 > 45 | 0 |
| | medium | 75 > 65 | 0 |
| | high | 70 ≤ 75 ≤ 90 (plateau) | **1** |

**Rule evaluation:** only R9 (hot AND high) fires, with w₉ = min(1, 1) = 1. All other
rules have w = 0.

**Implication and aggregation:** with w = 1 the clipped sets are the full `strong_cool`
and fan `high` sets.

**Centroid (hand calculation):**

- ac_power, strong_cool [40, 70, 100, 100]: rising triangle area 15, centroid 60;
  plateau area 30, centroid 85. z* = (15·60 + 30·85)/45 = **76.67 %**.
- fan_speed, high [60, 80, 100, 100]: triangle area 10, centroid 73.33; plateau area
  20, centroid 90. z* = (10·73.33 + 20·90)/30 = **84.44 %**.

The program outputs ac_power = 76.67 % (Cooling) and fan_speed = 84.44 %, the same as
the hand calculation. The direction makes physical sense: a hot, humid room gets
strong cooling, which also dehumidifies, and a high fan speed. See
`outputs/figures/worked_example_T32_H75.png`. As a further check, the hand-written
inference was compared with `skfuzzy.control` at eight operating points; the largest
difference was 6.8 × 10⁻⁵ %.

### 3.5 Control surfaces

`surface_ac_power.png` shows a monotonic, S-shaped surface from about −77 % (cold) to
+77 % (hot). It has a flat "off" plateau over the comfortable band at low and medium
humidity. Along the humidity axis, high humidity shifts the surface toward cooling.
At T = 20 °C and H = 68 %, the output is +2.1 % instead of the slight heating it would
otherwise be. `surface_fan_speed.png` increases from low (≈ 15 %) in cool, dry
conditions to high (≈ 84 %) in hot, humid ones.

---

## 4. Simulation Setup

**Plant model** (Δt = 1 min, 120 steps):

  T[k+1] = T[k] + k₁ (T_out − T[k]) − k₂ · ac[k]/100

  H[k+1] = H[k] − k₃ · (ac[k]/100 if ac[k] > 0 else 0) + k₄ (H_out − H[k]),  H ∈ [20, 90]

| Parameter | Value | Meaning |
|---|---|---|
| k₁ | 0.02 min⁻¹ | heat leakage through the envelope |
| k₂ | 0.5 °C/min | temperature change at 100 % AC power |
| k₃ | 0.3 %/min | dehumidification at 100 % cooling |
| k₄ | 0.01 min⁻¹ | humidity drift toward outdoor value |

**Scenarios**

| | Description | T₀ (°C) | H₀ (%) | T_out (°C) | H_out (%) |
|---|---|---|---|---|---|
| A | Hot humid day | 34 | 75 | 36 | 80 |
| B | Cold day | 14 | 40 | 10 | 40 |
| C | Mild day | 26 | 60 | 27 | 60 |

**Baseline:** ON/OFF thermostat with setpoint 23.5 °C and ±1 °C hysteresis.
Cooling (+100 %) switches on when T > 24.5 °C and off when T ≤ 23.5 °C.
Heating (−100 %) switches on when T < 22.5 °C and off when T ≥ 23.5 °C.

**Metrics:** comfort zone 22–25 °C.

| Metric | Definition |
|---|---|
| Settling time | first minute after which T stays in 22–25 °C until the end of the run |
| Max overshoot | max excursion past 23.5 °C on the side opposite to T₀ |
| Steady-state error | mean \|T − 23.5\| over the last 30 min |
| Energy | Σₖ \|ac[k]\| (%·min) |
| Switching events | changes between heating, idle and cooling; \|ac\| < 5 % counts as idle |
| Energy saving | (E_ON/OFF − E_fuzzy) / E_ON/OFF × 100 % |

All quantities are deterministic. No random noise is used.

---

## 5. Results

Values from `python main.py` (also saved to `outputs/results.csv`):

| Scenario | Controller | Settling time | Max overshoot (°C) | SS error (°C) | Energy (%·min) | Switching events | Time in comfort (%) | Final T (°C) | Energy saving (%) |
|---|---|---|---|---|---|---|---|---|---|
| A) Hot humid day | Fuzzy (Mamdani) | not settled | 0.00 | 1.74 | 6280.7 | 1 | 0.0 | 25.24 | **14.0** |
| A) Hot humid day | ON/OFF thermostat | 25 min | 0.23 | 0.55 | 7300.0 | 19 | 79.3 | 23.66 | – |
| B) Cold day | Fuzzy (Mamdani) | not settled | 0.00 | 2.81 | 5994.8 | 1 | 0.0 | 20.69 | **21.1** |
| B) Cold day | ON/OFF thermostat | 24 min | 0.22 | 0.52 | 7600.0 | 20 | 80.2 | 23.13 | – |
| C) Mild day | Fuzzy (Mamdani) | 6 min | 0.00 | 0.24 | 1948.9 | 1 | 95.0 | 23.82 | **−8.3** |
| C) Mild day | ON/OFF thermostat | 3 min | 0.32 | 0.52 | 1800.0 | 10 | 97.5 | 24.36 | – |

Figures: `outputs/figures/simulation_A.png`, `simulation_B.png`, `simulation_C.png`.

**Scenario A (hot, humid).** The FLC starts at its maximum cooling command (76.7 %)
and reduces it smoothly as the room cools. It levels off at about 43 %. The room
approaches 25.24 °C asymptotically, only 0.24 °C above the comfort limit, and never
overshoots. Humidity falls from 75 % to about 68 %. The thermostat runs at 100 %
until minute 31, then cycles between 23.3 and 24.7 °C, with 19 switching events.

**Scenario B (cold).** The FLC heats at −72 % and then levels off at about −43 %. The
room settles at 20.69 °C. The thermostat reaches the zone in 24 min and cycles between
22.3 and 23.7 °C, with 20 switching events.

**Scenario C (mild).** Both controllers keep the room comfortable. The FLC enters the
comfort zone in 6 min and holds it at 23.6–23.8 °C with a gently decreasing cooling
command (about 17 % → 12 %). Its steady-state error (0.24 °C) is less than half that of the thermostat
(0.52 °C), with 1 switching event versus 10. The thermostat used 8.3 % less energy
here.

---

## 6. Comparison & Discussion

**Smoothness and actuator wear.** The FLC's greatest advantage is the quality of the
control action. It produced one mode change per run against 10–20 for the
thermostat, with zero overshoot in every scenario. For a real compressor this means
far fewer start-stop cycles, less inrush current and less mechanical wear. Quieter
operation and steadier temperature also improve occupant comfort. ON/OFF cycling
produced a saw-tooth of about 1.4 °C peak to peak (23.3–24.7 °C in scenario A).

**Steady-state offset: an honest reading of the energy figures.** In scenarios A and
B the FLC used 14–21 % less energy but **never entered** the comfort zone. This is
structural, not a tuning accident. The FLC is a static map from the *current* state
to the command, so it behaves like a nonlinear **proportional** controller with no
integral action. At steady state, the AC must exactly cancel the envelope heat flow:

  k₂ · ac/100 = k₁ (T_out − T)  ⇒  ac = 4 (T_out − T)

In scenario A, holding 23.5 °C against 36 °C outside needs ac = 50 %. The rule base
only commands strong cooling when the room is clearly "hot" (μ_hot grows from 24 °C).
Around 25 °C the `comfortable → off` rules dominate, and the two curves cross at
T ≈ 25.2 °C, where ac = 4 × (36 − 25.24) ≈ 43 %. This is exactly what the simulation
shows. In scenario B the same analysis gives ac = 4 × (20.69 − 10) ≈ −43 %, at the
point where `cold` has faded and `comfortable → off` takes over. Part of the "saving"
in A and B is therefore lost comfort. A room held 1–3 °C away from the setpoint needs
less power to maintain. In scenario C the load is small (ac ≈ 4 × 3.3 ≈ 13 %), the
offset is negligible, and the FLC has better steady-state accuracy than the thermostat.
In that case the thermostat was 8.3 % more efficient, because it lets the room drift
to the upper edge of its band before cooling again.

**Rise time.** The thermostat always applies 100 % power, whereas the centroid
limits the FLC to 76.7 %. The thermostat therefore reaches the zone faster when it
does reach it (3 min vs 6 min in C). The FLC's softer action is the trade-off for its
smoothness.

**Humidity.** In scenario A, rules R6 and R9 couple humidity to the cooling effort.
Continuous moderate cooling removed moisture steadily (75 % → 68 %), which a
temperature-only thermostat does not consider at all.

**Summary.** The Mamdani FLC is clearly better in smoothness, switching count,
overshoot and (for light loads) steady-state accuracy. Its energy advantage under
heavy loads cannot be separated from a comfort penalty. The thermostat is better at
holding the setpoint *on average* under heavy loads, at the cost of constant cycling.
A practical design should combine the FLC's smooth action with an integral or
setpoint-error mechanism (see Future Scope).

**Limitations.** The plant model is first order, with no thermal mass, sensor lag or
compressor minimum run time. The fan speed does not influence the plant. The outdoor
conditions are constant, and energy is measured as an abstract Σ|ac|, not kWh with
a COP model.

---

## 7. Extensions

The first version of this project showed one clear weakness: the steady-state offset
of the 9-rule controller. It also listed several items as future work. This section
implements and evaluates them. All numbers come from `python main.py`
(`outputs/results*.csv`).

### 7.1 Improved controller: incremental Fuzzy PI

The offset exists because the 9-rule FIS has no memory. The improved controller
(`fuzzy_pi.py`) uses the error and its rate of change, and outputs a *change* in
command:

  e[k] = T_f[k] − T_sp(H[k]),  Δe[k] = e[k] − e[k−1],  u[k] = clip(u[k−1] + FIS(e, Δe), −100, 100)

- **Inputs.** The error e (°C) has five terms: NB, NS, ZE, PS, PB. The change of error
  Δe (°C/min) has three: N, Z, P.
- **Output.** The change of command Δu (%/min) has five terms. Inference is Mamdani,
  exactly as in the main FIS.
- **Integral action.** The summation u[k−1] + Δu is the integral action. Clipping u to
  ±100 % is the anti-windup.
- **Humidity compensation.** T_sp(H) = 23.5 − 0.5·μ_high(H), using the main FIS's own
  humidity set.
- **Measurement filter.** T_f is a first-order low-pass filter of the reading
  (α = 0.5), because differencing amplifies sensor noise.

Rule table (rows e, columns Δe):

| e \ Δe | N | Z | P |
|---|---|---|---|
| NB | NB | NB | NS |
| NS | NS | NS | PS |
| ZE | NB | ZE | PB |
| PS | NS | PS | PS |
| PB | PS | PB | PB |

The table is antisymmetric, so heating and cooling behave alike. The ZE row brakes hard
when the room passes the setpoint quickly. A first version, with a softer ZE row,
overshot by 1.49 °C in scenario A; this table overshoots by 0.38 °C.

| Scenario | Controller | Settling | Overshoot (°C) | SS error (°C) | kWh | Switches | Final T (°C) |
|---|---|---|---|---|---|---|---|
| A | Mamdani | not settled | 0.00 | 1.74 | 1.650 | 1 | 25.24 |
| A | **Fuzzy PI** | **29 min** | 0.38 | **0.38** | 1.954 | **1** | **23.13** |
| A | ON/OFF | 25 min | 0.23 | 0.55 | 1.898 | 19 | 23.66 |
| B | Mamdani | not settled | 0.00 | 2.81 | 1.521 | 1 | 20.69 |
| B | **Fuzzy PI** | **28 min** | 0.00 | **0.00** | 1.943 | **1** | **23.50** |
| B | ON/OFF | 24 min | 0.22 | 0.52 | 1.976 | 20 | 23.13 |
| C | Mamdani | 6 min | 0.00 | 0.24 | 0.520 | 1 | 23.82 |
| C | **Fuzzy PI** | 7 min | 0.06 | **0.06** | 0.561 | **1** | 23.45 |
| C | ON/OFF | 3 min | 0.32 | 0.52 | 0.468 | 10 | 24.36 |

The Fuzzy PI removes the offset: B settles at exactly 23.5 °C, and A settles at its
humidity-lowered target of about 23.1 °C. It also keeps the single switching event of
the Mamdani controller. It uses about as much energy as the thermostat (A −3.3 %,
B −1.1 % on the Σ|ac| basis) and more on the mild day (−17.6 %). The reason is that it
holds the setpoint itself, whereas the thermostat spends much of its time in the warmer
upper half of its band. **Better accuracy at equal comfort costs energy in this linear
power model.**

### 7.2 24-hour weather

Scenario D is a full summer day for an office occupied 09:00–18:00. The outdoor
temperature is 30 ± 6 °C (peak at 15:00), and outdoor humidity is 65 ± 15 %, highest at
dawn.

- **Fuzzy PI and thermostat.** Both keep 100 % of occupied time in the comfort zone.
  The thermostat switches **180 times**; the Fuzzy PI switches **5 times**.
- **Mamdani.** It reaches only 22 % because of its offset.
- **Energy.** The thermostat uses 9.20 kWh, against 10.32 kWh for the Fuzzy PI and
  10.24 kWh for the Mamdani controller.

### 7.3 Occupancy (eco dead band)

While the office is empty, the comfort band widens to 20–27 °C, as on a
dual-setpoint smart thermostat:

- **Inside the band**, the AC is off.
- **Beyond an edge (+0.5 °C hysteresis)**, the controller brings the room back to that
  edge, pushing in that direction only.
- **Pre-conditioning.** Normal control resumes 30 minutes before arrival.

An earlier version simply shifted the setpoint. It made the thermostat *heat* a 26 °C
room on a summer night, and it flickered at the band edge. Both faults were fixed with
the dead band described here.

| Controller | kWh always on | kWh with eco | Saved | Comfort while occupied | Switches |
|---|---|---|---|---|---|
| Fuzzy (Mamdani) | 10.24 | 6.48 | 36.7 % | 23 % | 8 |
| Fuzzy PI | 10.32 | 7.54 | 26.9 % | 100 % | 6 |
| ON/OFF | 9.20 | 7.02 | 23.7 % | 100 % | 130 |

Occupancy control saves 24–37 % for every controller at no loss of occupied comfort.
At ₹8/kWh this is ₹17–30 per day for one room.

### 7.4 Electrical energy and cost

The abstract energy figure Σ|ac| is complemented by electrical energy:

  kWh = Σ (|ac|/100 × 1.5 kW + fan/100 × 0.06 kW) / 60

This assumes a 1.5-ton inverter split AC and a 60 W indoor fan, with a tariff of
₹8/kWh (both editable in the dashboard). The model is **linear** in |ac|, so it gives
no credit for the higher part-load efficiency of inverter compressors, nor charges
the start-up losses of on/off cycling. Real-world results would therefore likely
favour the continuous fuzzy controllers more than these figures do.

### 7.5 Sensor noise

Gaussian noise was added to the readings the controllers see: σ = 0.2 °C (the DHT22
datasheet repeatability) and 2 %RH, with a fixed seed so results reproduce.

- **Fuzzy PI.** It is unaffected, thanks to its filter: B's steady-state error is
  0.08 °C and A still makes 1 switching event.
- **Thermostat.** Its hysteresis absorbs the noise (18–19 switches against 19–20
  without noise).
- **Negative result.** Noise did **not** make the thermostat chatter. It *did* make both
  fuzzy controllers flicker around the 5 % idle threshold on the mild day (Mamdani 1 → 27
  switching events, Fuzzy PI 1 → 19). The commands there are small (≈ 12 %), so noise
  pushes them across the idle line.
- **Remedy.** A real implementation should add hysteresis to the mode decision, or a
  minimum compressor run time (as the ESP32 sketch does).

### 7.6 Rule & MF editor

The dashboard's editor tab lets a user change any membership-function parameter or
rule consequent. It then shows:

- the original and edited control surfaces side by side;
- the original controller, the edited one and the thermostat on the selected scenario;
- an export of the edited design as JSON or as an ESP32 lookup table.

Invalid parameters are rejected with a clear message: they must be non-decreasing,
inside the universe and of non-zero width.

### 7.7 Hardware: ESP32 + DHT22

`hardware/export_lut.py` samples the FIS on a 0.5 °C × 1 %RH grid (61 × 71 points,
16.9 KB of int16 flash). The sketch `hardware/esp32_fuzzy_ac/esp32_fuzzy_ac.ino`
interpolates the table bilinearly. Over 42,441 test points, the mean error is 0.06 %
of AC power (worst case 5.0 %, at the steepest edge of the surface).

The sketch also implements:

- input clamping, as in `compute()`;
- a fail-safe shut-down after 3 bad sensor reads;
- relays that never cool and heat at the same time;
- a 3-minute compressor rest between modes;
- PIR occupancy with the same eco dead band as the simulation;
- CSV telemetry over serial.

It compiles cleanly (`-Wall -Wextra`) against both the ESP32 Arduino core 2.x and 3.x
LEDC APIs, checked with stub headers. **It has not yet been run on physical hardware.**

### 7.8 Live Room view and verification

The dashboard's Live Room tab animates one illustrated room per controller:

- walls tinted by temperature;
- a window showing the weather outside;
- AC airflow, blue for cooling and red for heating, scaled by power;
- a ceiling fan at the commanded speed;
- the occupant, a thermometer with the comfort band, and a humidity dial;
- running energy totals.

It has Play/Pause, speed and a time slider, and runs entirely in the browser.

An automated test suite (`pytest`, 44 tests) checks:

- the worked example, fuzzification degrees and edge inputs;
- agreement with skfuzzy, and with the vectorised evaluator to 10⁻⁹;
- monotonic response, the antisymmetric PI table and offset removal;
- the thermostat's hysteresis, the metrics, noise reproducibility and eco-mode
  correctness;
- reproduction of the original specification's numbers;
- lookup-table accuracy, PDF generation and the room-view data.

---

## 8. Conclusion

A complete Mamdani fuzzy controller for room climate was designed, implemented,
verified and evaluated. The implementation matches hand calculation (76.67 % AC power
and 84.44 % fan speed at 32 °C / 75 %) and an independent scikit-fuzzy reference to
within 7 × 10⁻⁵ %.

Compared with an ON/OFF thermostat, the 9-rule controller removed overshoot and cut
switching events by 90–95 %. Its 14–21 % energy saving under heavy load came with a
steady-state offset (25.24 °C and 20.69 °C).

An incremental Fuzzy PI controller removed that offset. It settled at 23.5 °C in the
cold scenario and kept 100 % occupied comfort on a 24-hour day with 5 switching events
instead of 180. It uses about the same or slightly more energy than the thermostat
under a linear power model. Occupancy-based eco control saved a further 24–37 % for
every controller.

The design runs on an ESP32 through a 17 KB lookup table. The Streamlit dashboard
(live room animation, rule editor, PDF reports) makes the inference transparent for
teaching and tuning.

---

## 9. Future Scope

1. **Hardware trial.** Build the ESP32 + DHT22 + relay prototype in a real room and
   compare its logged data with the simulation.
2. **Part-load efficiency model.** Add an inverter COP curve and on/off cycling losses
   (e.g. a degradation coefficient C_d ≈ 0.25), so the energy comparison reflects real
   compressors.
3. **Mode hysteresis for the fuzzy controllers.** Prevent the noise-induced flicker
   around the idle threshold seen on the mild day.
4. **Adaptive and self-tuning rules.** Tune MFs and rules automatically with ANFIS, a
   genetic algorithm or reinforcement learning, minimising energy plus a discomfort
   penalty.
5. **Richer comfort index.** Use PMV/PPD (ISO 7730) or a heat index instead of a plain
   temperature band.
6. **Better plant model.** Add thermal mass, sensor lag, solar gain, the fan's effect
   on heat transfer, and CO₂-based occupancy counting.

---

## 10. References

1. E. H. Mamdani and S. Assilian, "An experiment in linguistic synthesis with a fuzzy
   logic controller," *International Journal of Man-Machine Studies*, vol. 7, no. 1,
   pp. 1–13, 1975.
2. L. A. Zadeh, "Fuzzy sets," *Information and Control*, vol. 8, no. 3, pp. 338–353,
   1965.
3. T. J. Ross, *Fuzzy Logic with Engineering Applications*, 4th ed. Wiley, 2016.
4. K. M. Passino and S. Yurkovich, *Fuzzy Control*. Addison-Wesley, 1998.
5. J. Jantzen, *Foundations of Fuzzy Control: A Practical Approach*, 2nd ed. Wiley,
   2013.
6. J. Warner *et al.*, "scikit-fuzzy: Fuzzy logic toolbox for Python," version 0.5,
   https://github.com/scikit-fuzzy/scikit-fuzzy.
7. ISO 7730:2005, *Ergonomics of the thermal environment — Analytical determination
   and interpretation of thermal comfort using calculation of the PMV and PPD indices
   and local thermal comfort criteria*.
8. ASHRAE Standard 55-2020, *Thermal Environmental Conditions for Human Occupancy*.
9. Streamlit Inc., *Streamlit documentation*, https://docs.streamlit.io.
