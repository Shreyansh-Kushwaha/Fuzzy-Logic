# ESP32 + DHT22 hardware version

The fuzzy controller runs on an ESP32 as a **lookup table**. `export_lut.py` samples
the Mamdani FIS every 0.5 °C and every 1 %RH (61 × 71 points, 16.9 KB of flash), and
the sketch interpolates between grid points. The mean error against the Python
controller is 0.06 % (worst case 5 %, at the steepest edge of the control surface).

> Status: the sketch compiles warning-free against ESP32 Arduino core 2.x and 3.x
> (checked with stub headers). It has **not yet been flashed to a real board**.

## Parts

- ESP32 dev board
- DHT22 (AM2302) temperature/humidity sensor and a 10 kΩ pull-up resistor
- HC-SR501 PIR motion sensor (optional, for occupancy eco mode)
- 2-channel opto-isolated relay module (COOL / HEAT mode select)
- For an inverter AC's 0–10 V demand input: an RC filter plus an op-amp on the
  compressor PWM pin; for a DC/EC fan: a MOSFET driver or the EC fan's PWM input

**Never switch mains directly from the ESP32.** Use isolated relay modules or the AC
unit's low-voltage control interface.

## Wiring

| Signal | ESP32 pin |
|---|---|
| DHT22 data (10 kΩ pull-up to 3.3 V) | GPIO 4 |
| PIR output | GPIO 14 |
| COOL relay | GPIO 26 |
| HEAT relay | GPIO 27 |
| Compressor power PWM (0–100 %) | GPIO 25 |
| Fan PWM (0–100 %) | GPIO 33 |

## Upload

1. Install the Arduino IDE and the ESP32 board package (Boards Manager → "esp32" by
   Espressif).
2. Install the libraries "DHT sensor library" (Adafruit) and "Adafruit Unified Sensor".
3. Optional: after editing the FIS (or exporting `fuzzy_lut.h` from the dashboard's
   Reports tab), regenerate the table with `python hardware/export_lut.py` from the
   project folder.
4. Open `esp32_fuzzy_ac/esp32_fuzzy_ac.ino`, select your board and port, then
   upload.
5. Open the Serial Monitor at 115200 baud. Every minute it prints a CSV line:
   `ms,temp_C,hum_pct,occupied,eco,ac_pct,fan_pct,mode`.

## What the sketch does

- **Control step:** reads the DHT22 once a minute (the same step as the simulation),
  clamps the readings to the table range and interpolates AC power and fan speed.
- **Mode switching:** the mode is cooling above +5 %, heating below −5 %, otherwise
  idle. Mode changes always pass through idle with a 3-minute compressor rest, and
  the COOL and HEAT relays are never on together.
- **Fail-safe:** after 3 failed sensor reads in a row, everything is switched off.
- **Occupancy eco mode:** after 30 minutes with no PIR motion, it uses the same eco
  dead band as the simulation. The AC is off between 20 and 27 °C, and beyond an edge
  (±0.5 °C hysteresis) it works back to that edge, in that direction only.
