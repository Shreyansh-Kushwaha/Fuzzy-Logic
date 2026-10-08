# Mamdani Fuzzy Logic Controller for Automatic Room Temperature Regulation

A two-input, two-output **Mamdani fuzzy inference system** drives a reversible AC unit
(heating ↔ cooling) and its fan from room **temperature** and **humidity**. An
improved **Fuzzy PI** controller removes the basic design's steady-state offset. Both
are compared with a classic **ON/OFF thermostat** on a simulated room. The project
also includes 24-hour weather, occupancy eco mode, sensor noise, kWh and cost, an
**animated Streamlit dashboard**, a **rule & MF editor**, **PDF reports**, an
**ESP32 + DHT22 sketch** and **44 automated tests**.

New to fuzzy logic? Start with [`EXPLAINED.md`](EXPLAINED.md). The full academic write-up
is in [`report.md`](report.md).

## Project structure

```
project/
├── fuzzy_controller.py   Mamdani engine + room FIS; compute(temp, hum) -> (ac_power, fan_speed, rule_strengths)
├── fuzzy_pi.py           improved incremental Fuzzy PI controller
├── simulation.py         room model, controllers, 24-h weather, occupancy eco, noise, metrics, kWh/cost
├── visualize.py          all matplotlib figures
├── room_view.py          animated "Live Room" (HTML/SVG/JS) for the dashboard
├── report_pdf.py         PDF report builder (matplotlib backend, no extra dependency)
├── main.py               runs everything, saves figures/tables/PDF, exports the ESP32 table
├── app.py                Streamlit dashboard
├── hardware/
│   ├── export_lut.py     FIS -> lookup table (fuzzy_lut.h) + accuracy check
│   ├── README.md         wiring and upload steps
│   └── esp32_fuzzy_ac/   Arduino sketch + generated fuzzy_lut.h
├── tests/                pytest suite (44 tests)
├── requirements.txt
├── README.md · EXPLAINED.md · report.md
└── outputs/              created by main.py: figures/*.png, results*.csv, results.md, report.pdf
```

## Setup

Requires Python 3.10 or newer.

```bash
cd project
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python main.py                                   # everything: tables, figures, PDF, ESP32 table (~45 s)
streamlit run app.py --server.port 6000          # dashboard at http://localhost:6000
python -m pytest                                 # 44 tests (~15 s)
python hardware/export_lut.py                    # only regenerate the ESP32 lookup table
```

## Dashboard tabs

| Tab | What you can do |
|---|---|
| **Controller** | Move the temperature/humidity sliders. See the outputs, an illustrated room, which rules fire, the membership functions, where the point sits on the control surface, and the Fuzzy PI design. |
| **Live Room** | Watch one animated room per controller side by side. Walls change colour with temperature; the AC blows blue (cool) or red (heat) air; the fan spins with fan speed. Includes a thermometer, humidity dial and occupant, with Play/Pause, speed and a time slider. |
| **Simulation** | Graphs and metrics (comfort, kWh, cost, switching) for the scenario, controllers, noise and occupancy chosen in the sidebar. |
| **Rule & MF Editor** | Edit any membership function or rule, then compare the original and edited surfaces and simulations. |
| **Reports & Downloads** | One-click PDF report, the full project PDF, CSVs, the design as JSON, and an ESP32 `fuzzy_lut.h` for the edited design. |

## Design summary

**Mamdani FIS:** AND = min, implication = min, aggregation = max, defuzzification =
centroid. All universes use a 0.1 step.

| Temp \ Humidity | low | medium | high |
|---|---|---|---|
| **cold** | strong_heat, fan low | strong_heat, fan low | mild_heat, fan medium |
| **comfortable** | off, fan low | off, fan low | mild_cool, fan medium |
| **hot** | mild_cool, fan medium | strong_cool, fan high | strong_cool, fan high |

**Fuzzy PI:** `u[k] = clip(u[k−1] + FIS(e, Δe), −100, 100)`, with 5 × 3 antisymmetric
rules. The setpoint is lowered by up to 0.5 °C in humid air, and the temperature input
passes through a low-pass filter.

**Room model (1-min step):**
`T+ = T + 0.02(T_out − T) − 0.5·ac/100`,
`H+ = H − 0.3·(ac/100 if cooling) + 0.01(H_out − H)`.

**ON/OFF:** 23.5 °C ± 1 °C. It switches on beyond ±1 °C and off at the setpoint.

**Electricity:** 1.5 kW AC at 100 % plus a 60 W fan, at ₹8/kWh (editable in the
dashboard).

## Key results (`python main.py`)

| Scenario | Controller | Settling | SS error (°C) | kWh | Switches | Final T (°C) |
|---|---|---|---|---|---|---|
| A) Hot humid | Mamdani | not settled | 1.74 | 1.65 | 1 | 25.24 |
| A) Hot humid | Fuzzy PI | 29 min | 0.38 | 1.95 | 1 | 23.13 |
| A) Hot humid | ON/OFF | 25 min | 0.55 | 1.90 | 19 | 23.66 |
| B) Cold | Mamdani | not settled | 2.81 | 1.52 | 1 | 20.69 |
| B) Cold | Fuzzy PI | 28 min | 0.00 | 1.94 | 1 | 23.50 |
| B) Cold | ON/OFF | 24 min | 0.52 | 1.98 | 20 | 23.13 |
| C) Mild | Mamdani | 6 min | 0.24 | 0.52 | 1 | 23.82 |
| C) Mild | Fuzzy PI | 7 min | 0.06 | 0.56 | 1 | 23.45 |
| C) Mild | ON/OFF | 3 min | 0.52 | 0.47 | 10 | 24.36 |
| D) 24-h office | Fuzzy PI | — | 0.28 | 10.32 | 5 | 100 % occupied comfort |
| D) 24-h office | ON/OFF | — | 0.42 | 9.20 | 180 | 100 % occupied comfort |

- **Mamdani:** smooth, but with an offset under heavy load.
- **Fuzzy PI:** removes the offset with 1–5 switches.
- **ON/OFF:** fastest and slightly cheaper in this linear power model, but switches
  10–180 times.
- **Occupancy eco mode:** saves 24–37 % on day D for every controller.

Full tables, including the noise study, are in `outputs/results.md`; the discussion is
in `report.md` §6–7.

## Reproducibility

There is no unseeded randomness. Sensor noise uses a fixed seed (42), so `main.py`
gives identical tables and figures on every run.
