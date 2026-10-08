## Main comparison

| Scenario | Controller | Settling time | Max overshoot (°C) | SS error (°C) | Energy (%·min) | Energy (kWh) | Cost (₹) | Switching events | Comfort (% of occupied time) | Discomfort (°C·min) | Final T (°C) | Energy saving vs ON/OFF (%) | kWh saving vs ON/OFF (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A) Hot humid day | Fuzzy (Mamdani) | not settled | 0.0 | 1.74 | 6280.7 | 1.65 | 13.2 | 1 | 0.0 | 188.0 | 25.24 | 14.0 | 13.1 |
| A) Hot humid day | Fuzzy PI | 29 min | 0.38 | 0.38 | 7539.6 | 1.954 | 15.63 | 1 | 75.8 | 139.8 | 23.13 | -3.3 | -2.9 |
| A) Hot humid day | ON/OFF thermostat | 25 min | 0.23 | 0.55 | 7300.0 | 1.898 | 15.18 | 19 | 79.2 | 106.0 | 23.66 | - | - |
| B) Cold day | Fuzzy (Mamdani) | not settled | 0.0 | 2.81 | 5994.8 | 1.521 | 12.17 | 1 | 0.0 | 275.9 | 20.69 | 21.1 | 23.0 |
| B) Cold day | Fuzzy PI | 28 min | 0.0 | 0.0 | 7684.4 | 1.943 | 15.55 | 1 | 76.7 | 122.0 | 23.5 | -1.1 | 1.7 |
| B) Cold day | ON/OFF thermostat | 24 min | 0.22 | 0.52 | 7600.0 | 1.976 | 15.81 | 20 | 80.0 | 91.4 | 23.13 | - | - |
| C) Mild day | Fuzzy (Mamdani) | 6 min | 0.0 | 0.24 | 1948.9 | 0.52 | 4.16 | 1 | 95.0 | 3.3 | 23.82 | -8.3 | -11.1 |
| C) Mild day | Fuzzy PI | 7 min | 0.06 | 0.06 | 2117.7 | 0.561 | 4.49 | 1 | 94.2 | 4.5 | 23.45 | -17.6 | -20.0 |
| C) Mild day | ON/OFF thermostat | 3 min | 0.32 | 0.52 | 1800.0 | 0.468 | 3.74 | 10 | 97.5 | 1.6 | 24.36 | - | - |
| D) 24-hour summer day (office) | Fuzzy (Mamdani) | not settled | 2.62 | 1.63 | 38542.0 | 10.241 | 81.93 | 1 | 22.4 | 192.4 | 21.73 | -8.9 | -11.3 |
| D) 24-hour summer day (office) | Fuzzy PI | 10 min | 0.52 | 0.28 | 39410.6 | 10.315 | 82.52 | 5 | 100.0 | 0.0 | 23.18 | -11.3 | -12.1 |
| D) 24-hour summer day (office) | ON/OFF thermostat | 6 min | 0.45 | 0.42 | 35400.0 | 9.204 | 73.63 | 180 | 100.0 | 0.0 | 24.38 | - | - |

## With sensor noise

| Scenario | Controller | Settling time | Max overshoot (°C) | SS error (°C) | Energy (%·min) | Energy (kWh) | Cost (₹) | Switching events | Comfort (% of occupied time) | Discomfort (°C·min) | Final T (°C) | Energy saving vs ON/OFF (%) | kWh saving vs ON/OFF (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A) Hot humid day + noise | Fuzzy (Mamdani) | not settled | 0.0 | 1.78 | 6272.8 | 1.648 | 13.18 | 1 | 0.0 | 188.6 | 25.26 | 11.7 | 10.7 |
| A) Hot humid day + noise | Fuzzy PI | 29 min | 0.56 | 0.35 | 7531.7 | 1.951 | 15.61 | 1 | 75.8 | 141.4 | 23.17 | -6.1 | -5.7 |
| A) Hot humid day + noise | ON/OFF thermostat | 25 min | 0.36 | 0.58 | 7100.0 | 1.846 | 14.77 | 18 | 79.2 | 106.0 | 24.62 | - | - |
| B) Cold day + noise | Fuzzy (Mamdani) | not settled | 0.0 | 2.96 | 5928.0 | 1.504 | 12.03 | 1 | 0.0 | 283.6 | 20.51 | 23.0 | 24.9 |
| B) Cold day + noise | Fuzzy PI | 28 min | 0.23 | 0.08 | 7658.2 | 1.936 | 15.49 | 1 | 76.7 | 123.6 | 23.4 | 0.5 | 3.3 |
| B) Cold day + noise | ON/OFF thermostat | 24 min | 0.38 | 0.52 | 7700.0 | 2.002 | 16.02 | 19 | 80.0 | 91.4 | 23.63 | - | - |
| C) Mild day + noise | Fuzzy (Mamdani) | 6 min | 0.0 | 0.4 | 1855.0 | 0.497 | 3.98 | 27 | 95.0 | 3.2 | 24.03 | 2.4 | -0.6 |
| C) Mild day + noise | Fuzzy PI | 7 min | 0.3 | 0.07 | 2161.1 | 0.572 | 4.58 | 19 | 94.2 | 4.4 | 23.41 | -13.7 | -15.8 |
| C) Mild day + noise | ON/OFF thermostat | 3 min | 0.42 | 0.42 | 1900.0 | 0.494 | 3.95 | 12 | 97.5 | 1.6 | 23.84 | - | - |

## Occupancy (eco setback)

| Scenario | Controller | Settling time | Max overshoot (°C) | SS error (°C) | Energy (%·min) | Energy (kWh) | Cost (₹) | Switching events | Comfort (% of occupied time) | Discomfort (°C·min) | Final T (°C) | Energy saving vs ON/OFF (%) | kWh saving vs ON/OFF (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D) always on | Fuzzy (Mamdani) | not settled | 2.62 | 1.63 | 38542.0 | 10.241 | 81.93 | 1 | 22.4 | 192.4 | 21.73 | -8.9 | -11.3 |
| D) always on | Fuzzy PI | 10 min | 0.52 | 0.28 | 39410.6 | 10.315 | 82.52 | 5 | 100.0 | 0.0 | 23.18 | -11.3 | -12.1 |
| D) always on | ON/OFF thermostat | 6 min | 0.45 | 0.42 | 35400.0 | 9.204 | 73.63 | 180 | 100.0 | 0.0 | 24.38 | - | - |
| D) with occupancy eco | Fuzzy (Mamdani) | not settled | 0.03 | 3.26 | 24706.1 | 6.48 | 51.84 | 8 | 23.3 | 191.6 | 26.54 | 8.5 | 7.7 |
| D) with occupancy eco | Fuzzy PI | not settled | 0.49 | 3.0 | 29177.7 | 7.537 | 60.3 | 6 | 100.0 | 0.0 | 26.35 | -8.1 | -7.4 |
| D) with occupancy eco | ON/OFF thermostat | not settled | 0.31 | 3.43 | 27000.0 | 7.02 | 56.16 | 130 | 100.0 | 0.0 | 26.67 | - | - |
