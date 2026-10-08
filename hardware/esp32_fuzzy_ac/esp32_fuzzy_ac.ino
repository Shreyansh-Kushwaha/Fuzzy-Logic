/*
  esp32_fuzzy_ac.ino
  ==================
  Mamdani fuzzy room-climate controller on an ESP32 with a DHT22 sensor.

  The fuzzy inference itself was done offline: hardware/export_lut.py samples
  the project's FIS (temperature x humidity -> AC power, fan speed) on a
  0.5 degC x 1 %RH grid and writes fuzzy_lut.h. Here we only interpolate the
  table, so each control step takes microseconds and gives exactly the
  outputs the Python controller would give (mean error 0.06 %).

  Wiring (change the pin numbers below to match your board)
  ---------------------------------------------------------
    DHT22 data        -> GPIO 4   (with a 10 kOhm pull-up to 3.3 V)
    PIR motion sensor -> GPIO 14  (HC-SR501 output, optional occupancy input)
    COOL relay        -> GPIO 26  (selects cooling mode on the AC / heat pump)
    HEAT relay        -> GPIO 27  (selects heating mode; never on with COOL)
    Compressor PWM    -> GPIO 25  (0-100 % power; RC filter + op-amp gives 0-10 V
                                   for an inverter's analogue demand input)
    Fan PWM           -> GPIO 33  (EC fan or MOSFET-driven DC fan)

  Never drive mains loads directly from the ESP32: use opto-isolated relay
  modules or the AC unit's low-voltage control interface.

  Libraries
  ---------
    "DHT sensor library" by Adafruit (+ "Adafruit Unified Sensor")
    ESP32 Arduino core 2.x or 3.x (both LEDC APIs are handled below)

  Serial output (115200 baud), one CSV line per control step:
    ms,temp_C,hum_pct,occupied,eco,ac_pct,fan_pct,mode
*/

#include <Arduino.h>
#include <DHT.h>
#include <math.h>
#include "fuzzy_lut.h"

// ---------------------------------------------------------------- pins ----
#define DHT_PIN            4
#define DHT_TYPE           DHT22
#define PIR_PIN            14
#define COOL_RELAY_PIN     26
#define HEAT_RELAY_PIN     27
#define COMPRESSOR_PWM_PIN 25
#define FAN_PWM_PIN        33

// ------------------------------------------------------------ settings ----
const uint32_t CONTROL_PERIOD_MS    = 60UL * 1000UL;       // 1-minute step, as in the simulation
const uint32_t MIN_OFF_TIME_MS      = 3UL * 60UL * 1000UL;  // compressor protection between modes
const uint32_t VACANCY_TIMEOUT_MS   = 30UL * 60UL * 1000UL; // no motion this long -> room empty
const float    MODE_THRESHOLD       = 5.0f;                 // |ac| below this = idle (as in Python)
const float    ECO_LOW_C            = 20.0f;                // widened band while empty ...
const float    ECO_HIGH_C           = 27.0f;                // ... (same as the simulation)
const float    ECO_HYSTERESIS_C     = 0.5f;
const float    SETPOINT_C           = 23.5f;
const uint8_t  MAX_SENSOR_FAILURES  = 3;                    // then fail safe: everything off
const bool     USE_OCCUPANCY_SENSOR = true;

const uint32_t PWM_FREQ_HZ = 5000;
const uint8_t  PWM_BITS    = 10;                            // duty 0..1023
#if !defined(ESP_ARDUINO_VERSION_MAJOR) || ESP_ARDUINO_VERSION_MAJOR < 3
const uint8_t  COMPRESSOR_CH = 0;
const uint8_t  FAN_CH        = 1;
#endif

enum Mode { MODE_IDLE = 0, MODE_COOL = 1, MODE_HEAT = -1 };

DHT dht(DHT_PIN, DHT_TYPE);

Mode     currentMode      = MODE_IDLE;
uint32_t modeOffSinceMs   = 0;
uint32_t lastControlMs    = 0;
uint32_t lastMotionMs     = 0;
uint8_t  sensorFailures   = 0;
bool     firstStep        = true;
int8_t   ecoDir           = 0;    // 0 AC off in eco band, +1 cooling back to 27, -1 heating back to 20

// --------------------------------------------------------------- LUT ------
// Bilinear interpolation in a [LUT_H_N][LUT_T_N] table of tenths of a percent.
// Identical to lut_lookup() in hardware/export_lut.py.
float lutLookup(const int16_t table[LUT_H_N][LUT_T_N], float temp, float hum) {
  temp = constrain(temp, LUT_T_MIN, LUT_T_MAX);   // clamp, like compute() in Python
  hum  = constrain(hum,  LUT_H_MIN, LUT_H_MAX);
  float ft = (temp - LUT_T_MIN) / LUT_T_STEP;
  float fh = (hum  - LUT_H_MIN) / LUT_H_STEP;
  int i0 = min((int)ft, LUT_T_N - 2);
  int j0 = min((int)fh, LUT_H_N - 2);
  float dt = ft - i0;
  float dh = fh - j0;
  float v00 = table[j0][i0];
  float v10 = table[j0][i0 + 1];
  float v01 = table[j0 + 1][i0];
  float v11 = table[j0 + 1][i0 + 1];
  float v = v00 * (1 - dt) * (1 - dh) + v10 * dt * (1 - dh)
          + v01 * (1 - dt) * dh       + v11 * dt * dh;
  return v / 10.0f;
}

// ------------------------------------------------------------ outputs -----
void pwmSetup() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(COMPRESSOR_PWM_PIN, PWM_FREQ_HZ, PWM_BITS);
  ledcAttach(FAN_PWM_PIN, PWM_FREQ_HZ, PWM_BITS);
#else
  ledcSetup(COMPRESSOR_CH, PWM_FREQ_HZ, PWM_BITS);
  ledcSetup(FAN_CH, PWM_FREQ_HZ, PWM_BITS);
  ledcAttachPin(COMPRESSOR_PWM_PIN, COMPRESSOR_CH);
  ledcAttachPin(FAN_PWM_PIN, FAN_CH);
#endif
}

void pwmWritePercent(uint8_t pin, float percent) {
  uint32_t duty = (uint32_t)(constrain(percent, 0.0f, 100.0f) / 100.0f * ((1 << PWM_BITS) - 1));
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(pin, duty);
#else
  ledcWrite(pin == COMPRESSOR_PWM_PIN ? COMPRESSOR_CH : FAN_CH, duty);
#endif
}

// Applies a command. Mode changes go through IDLE and respect MIN_OFF_TIME_MS
// so the compressor is never switched straight from cooling to heating.
Mode applyOutputs(float acPct, float fanPct, uint32_t now) {
  Mode wanted = MODE_IDLE;
  if (acPct >= MODE_THRESHOLD)       wanted = MODE_COOL;
  else if (acPct <= -MODE_THRESHOLD) wanted = MODE_HEAT;

  if (wanted != currentMode) {
    if (currentMode != MODE_IDLE) {             // stop first
      currentMode = MODE_IDLE;
      modeOffSinceMs = now;
    } else if (now - modeOffSinceMs >= MIN_OFF_TIME_MS || firstStep) {
      currentMode = wanted;                     // start the new mode
    }
  }

  digitalWrite(COOL_RELAY_PIN, currentMode == MODE_COOL ? HIGH : LOW);
  digitalWrite(HEAT_RELAY_PIN, currentMode == MODE_HEAT ? HIGH : LOW);
  pwmWritePercent(COMPRESSOR_PWM_PIN, currentMode == MODE_IDLE ? 0.0f : fabsf(acPct));
  pwmWritePercent(FAN_PWM_PIN, fanPct);
  return currentMode;
}

void allOff() {
  currentMode = MODE_IDLE;
  digitalWrite(COOL_RELAY_PIN, LOW);
  digitalWrite(HEAT_RELAY_PIN, LOW);
  pwmWritePercent(COMPRESSOR_PWM_PIN, 0);
  pwmWritePercent(FAN_PWM_PIN, 0);
}

// -------------------------------------------------------------- control ---
void controlStep(uint32_t now) {
  float temp = dht.readTemperature();   // degC
  float hum  = dht.readHumidity();      // %RH

  if (isnan(temp) || isnan(hum)) {
    sensorFailures++;
    Serial.printf("%lu,sensor_error,%u\n", (unsigned long)now, sensorFailures);
    if (sensorFailures >= MAX_SENSOR_FAILURES) allOff();   // fail safe
    return;                                                // else keep last command
  }
  sensorFailures = 0;

  bool occupied = !USE_OCCUPANCY_SENSOR || (now - lastMotionMs < VACANCY_TIMEOUT_MS);
  bool eco = !occupied && !firstStep;

  // Eco dead band, as in the simulation: while the room is empty the AC stays
  // off inside 20-27 degC. Beyond an edge (plus hysteresis) the controller
  // regulates back to that edge, seeing the temperature shifted so the edge
  // looks like the normal setpoint, and may only push in that one direction.
  float acPct, fanPct;
  if (eco) {
    if (ecoDir == 0) {
      if (temp > ECO_HIGH_C + ECO_HYSTERESIS_C)     ecoDir = 1;
      else if (temp < ECO_LOW_C - ECO_HYSTERESIS_C) ecoDir = -1;
    } else if ((ecoDir > 0 && temp <= ECO_HIGH_C - ECO_HYSTERESIS_C) ||
               (ecoDir < 0 && temp >= ECO_LOW_C + ECO_HYSTERESIS_C)) {
      ecoDir = 0;
    }
  } else {
    ecoDir = 0;
  }

  if (eco && ecoDir == 0) {
    acPct = 0.0f;
    fanPct = 0.0f;
  } else {
    float tempSeen = temp;
    if (ecoDir > 0) tempSeen = temp - (ECO_HIGH_C - SETPOINT_C);
    if (ecoDir < 0) tempSeen = temp + (SETPOINT_C - ECO_LOW_C);
    acPct  = lutLookup(AC_LUT, tempSeen, hum);
    fanPct = lutLookup(FAN_LUT, tempSeen, hum);
    if (ecoDir > 0) acPct = max(acPct, 0.0f);
    if (ecoDir < 0) acPct = min(acPct, 0.0f);
  }
  Mode mode = applyOutputs(acPct, fanPct, now);
  firstStep = false;

  const char* modeName = mode == MODE_COOL ? "cooling" : (mode == MODE_HEAT ? "heating" : "idle");
  Serial.printf("%lu,%.1f,%.1f,%d,%d,%.1f,%.1f,%s\n", (unsigned long)now, temp, hum,
                occupied ? 1 : 0, eco ? 1 : 0, acPct, fanPct, modeName);
}

// ------------------------------------------------------------- Arduino ----
void setup() {
  Serial.begin(115200);
  pinMode(COOL_RELAY_PIN, OUTPUT);
  pinMode(HEAT_RELAY_PIN, OUTPUT);
  pinMode(PIR_PIN, INPUT);
  pwmSetup();
  allOff();
  dht.begin();
  lastMotionMs = millis();
  modeOffSinceMs = millis();
  delay(2000);                          // DHT22 needs ~2 s after power-up
  Serial.println("ms,temp_C,hum_pct,occupied,eco,ac_pct,fan_pct,mode");
  controlStep(millis());
  lastControlMs = millis();
}

void loop() {
  uint32_t now = millis();
  if (digitalRead(PIR_PIN) == HIGH) lastMotionMs = now;
  if (now - lastControlMs >= CONTROL_PERIOD_MS) {
    lastControlMs = now;
    controlStep(now);
  }
  delay(50);
}
