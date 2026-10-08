# Fuzzy Room Temperature Controller — Plain-English Guide

We built a smarter air-conditioner "brain" that eases power up and down instead of
slamming it on and off. We then tested it against a normal thermostat in a simulated
room.

---

## 1. The problem

A room needs an air conditioner that can both heat and cool, and something has to
decide how hard to run it. Most homes use a basic **thermostat**, which is a simple
on/off switch:

- Too hot: cooling at 100 %.
- Too cold: heating at 100 %.
- Otherwise: off.

It works, but it's crude. It slams on and off all the time, and the temperature
zig-zags up and down.

---

## 2. The idea: fuzzy logic

Fuzzy logic lets a computer use **degrees of truth instead of yes/no**, the way people
do. You wouldn't say "24.9 °C is fine but 25.0 °C is hot". You'd say "it's a bit
warm" or "it's quite hot".

So instead of a sharp cut-off, a reading can be partly true for several words at once.
For example, 26 °C is:

- 40 % "comfortable"
- 33 % "hot"

---

## 3. How our controller works

It reads two sensors and makes two decisions:

| Reads (inputs) | Decides (outputs) |
|---|---|
| **Temperature** (10–40 °C) | **AC power**, from −100 % (full heating) to +100 % (full cooling) |
| **Humidity** (20–90 %) | **Fan speed** (0–100 %) |

It does this in four steps. **Mamdani** is just the name of this classic four-step
recipe, after Ebrahim Mamdani, who introduced it in 1975.

**Step 1: Turn numbers into words ("fuzzification").**
Each reading is described with word labels, each with a score from 0 to 1:
- Temperature: cold, comfortable, hot
- Humidity: low, medium, high

The overlapping triangle and trapezoid shapes in `outputs/figures/mf_temperature.png`
and `mf_humidity.png` define these labels.

**Step 2: Apply common-sense rules.**
We wrote 9 rules, like an expert's rules of thumb:

| Temperature ↓ / Humidity → | low | medium | high |
|---|---|---|---|
| **cold** | heat strongly, fan low | heat strongly, fan low | heat mildly, fan medium |
| **comfortable** | AC off, fan low | AC off, fan low | cool mildly, fan medium |
| **hot** | cool mildly, fan medium | cool strongly, fan high | cool strongly, fan high |

Read it like this: "**If** it's hot **and** humidity is high, **then** cool strongly
with a high fan."

A rule fires only as strongly as its **weakest** condition. If it's 70 % hot but only
30 % humid, the "hot and humid" rule fires at 30 %. In the code this is the
"AND = min" setting.

**Step 3: Blend the answers.**
Several rules can fire at once, each partly. Each one votes for an action, such as
"cool strongly" or "AC off", weighted by how strongly it fired. The votes are combined
into one overall shape. In the code this is the "implication = min, aggregation = max"
setting.

**Step 4: Turn words back into a number ("defuzzification").**
We take the **balance point (the centroid)** of that combined shape. That gives one
exact number, such as "run the AC at 43 % cooling".

Because it's a balance point, the output can never quite reach the ends of the range.
The strongest the controller ever asks for is about **±76.7 %**.

---

## 4. Worked example: 32 °C and 75 % humidity

1. **Words:** 32 °C is 100 % "hot" (0 % cold, 0 % comfortable). 75 % humidity is
   100 % "high" (0 % low, 0 % medium).
2. **Rules:** only one rule fires: "hot and humid, so cool strongly with a high fan",
   at strength 1.0.
3. **Blend:** the only shapes in play are "cool strongly" and "fan high".
4. **Number:** their balance points are **AC power 76.67 % (cooling)** and
   **fan speed 84.44 %**.

I checked this by hand and against scikit-fuzzy's built-in version, and the numbers
match. It also makes sense: a hot, sticky room gets strong cooling and a strong fan.
See `outputs/figures/worked_example_T32_H75.png`.

---

## 5. Testing it on a simulated room

We don't have a real room, so we wrote a simple equation-based model of one, updated
once per minute for 2 hours:

- Heat leaks in from outside when it's hotter outside, or out when it's colder.
- The AC pushes the temperature down (cooling) or up (heating). At full power it
  changes the room by 0.5 °C per minute.
- Cooling also dries the air.

We ran three "days":

| Day | Room starts at | Outside |
|---|---|---|
| A) Hot and humid | 34 °C, 75 % humidity | 36 °C, 80 % |
| B) Cold | 14 °C, 40 % humidity | 10 °C, 40 % |
| C) Mild | 26 °C, 60 % humidity | 27 °C, 60 % |

The goal is to keep the room in the **comfort zone of 22–25 °C**. We ran both the
fuzzy controller and a normal on/off thermostat (target 23.5 °C) on each day and
compared them.

---

## 6. What we found

| Day | Controller | Reached comfort zone? | Final temp | Energy used | On/off switches |
|---|---|---|---|---|---|
| A) Hot | Fuzzy | No, stopped just short | 25.2 °C | 14 % less | 1 |
| A) Hot | Thermostat | Yes, after 25 min | 23.7 °C | — | 19 |
| B) Cold | Fuzzy | No, stopped short | 20.7 °C | 21 % less | 1 |
| B) Cold | Thermostat | Yes, after 24 min | 23.1 °C | — | 20 |
| C) Mild | Fuzzy | Yes, after 6 min | 23.8 °C | 8 % more | 1 |
| C) Mild | Thermostat | Yes, after 3 min | 24.4 °C | — | 10 |

**Where the fuzzy controller did better:**
- **Smooth control.** It eases the AC up and down, with no slamming.
- **Very few switches.** It switched mode once per run, against 10–20 times for the
  thermostat. That's much easier on the compressor.
- **No overshoot.** It never went past the target.
- **Steadier on the mild day.** It held the room within 0.24 °C of the target on
  average, against 0.52 °C for the thermostat.

**Where it did worse:**
- **On the hot and cold days it never quite reached the comfort zone.** It eases off
  as the room becomes "fairly comfortable". Against a big temperature difference to
  the outside, it ends up just short.
- So part of its energy saving on those days comes from **not fully doing the job**.
  A room left slightly too warm or too cold needs less power to maintain.
- The thermostat always uses 100 % power, so it gets there faster.

**Bottom line:** fuzzy control gives smoother, gentler, more human-like control. With
these exact 9 rules, though, it needs one more ingredient to hit the target under
heavy load. That ingredient is some memory of how long it has been off target, which
engineers call "integral action". The report (`report.md`) suggests this as future
work.

---

## 7. What we added afterwards (the "full project" features)

### 7.1 A smarter fuzzy controller (Fuzzy PI)
The first controller stopped short of the comfort zone on the hot and cold days,
because it has no memory. It only looks at "how hot is it right now?". The new
**Fuzzy PI** controller asks two different questions:

- How far am I from 23.5 °C?
- Am I getting closer or further away, and how fast?

It then *nudges* the AC power up or down a little each minute, instead of jumping to a
fixed value. Those nudges keep adding up until the error is gone, which is what
engineers call "integral action".

**Result:** it reaches the target on every day (the cold day ends at exactly 23.5 °C)
and still switches only about once.

Two extra touches:
- In humid air it aims 0.5 °C cooler, because humid air feels warmer.
- It smooths the sensor reading first, so a jumpy sensor doesn't confuse it.

### 7.2 A full 24-hour day
Day **D** is a whole summer day in an office. It is cool at night and hottest at
3 pm, and people are in from 9:00 to 18:00. The Fuzzy PI and the thermostat both kept
the office comfortable all working day, but the thermostat switched **180 times**
against **5** for the Fuzzy PI.

### 7.3 Saving energy when nobody is there (occupancy eco mode)
When the office is empty, the comfort band relaxes to **20–27 °C**. The AC stays off
unless the room drifts outside that band, then gently brings it back to the edge. It
returns to normal 30 minutes before people arrive, so they walk into a comfortable
room.

**Result:** 24–37 % less electricity for every controller, with no loss of comfort
during working hours.

### 7.4 Real energy units and cost
Energy is now also shown in **kWh and rupees**. This assumes a 1.5-ton inverter AC
drawing 1.5 kW at full power, a 60 W fan, and ₹8 per kWh; you can change the price in
the dashboard.

**Honest finding:** in this simple model the thermostat is slightly cheaper. It lets
the room sit at the warm edge of its band, while the Fuzzy PI holds the exact target.
Real inverter ACs are more efficient at part power, which this model doesn't credit,
so real savings would probably favour fuzzy control more.

### 7.5 Sensor-noise test
Real sensors jitter a little, so we added realistic random noise (±0.2 °C, the DHT22
sensor's spec) with a fixed seed so results repeat exactly.

**Honest finding:** the Fuzzy PI handled it well. On the mild day, though, the noise
made both fuzzy controllers flicker around the 5 % "idle" line, while the thermostat
coped fine thanks to its built-in dead band. The fix (a minimum run time) is built into
the ESP32 version.

### 7.6 Rule & membership-shape editor
In the dashboard you can change any label shape (for example, what counts as "hot") or
any rule (for example, "hot and humid, so only mild cooling"). You then instantly see:

- how the decision map changes;
- how the room behaves with your version;
- and you can download your design.

### 7.7 Hardware version (ESP32 + DHT22)
A real microcontroller can run the same controller. We pre-calculate the controller's
answer for every 0.5 °C and every 1 % humidity and store it as a table (17 KB). The
ESP32 then just looks up the answer and blends between neighbouring entries. It agrees
with the Python version to within 0.06 % on average.

The sketch also includes:
- a safety shut-off if the sensor fails;
- a 3-minute rest for the compressor between modes;
- a motion sensor for eco mode.

Wiring and upload steps are in `hardware/README.md`. The code compiles, but it hasn't
been tried on a real board yet.

### 7.8 The Live Room
In the dashboard's **Live Room** tab, one cartoon room per controller plays side by
side:

- the walls turn blue when cold and red when hot;
- the AC blows blue air when cooling and red air when heating;
- the ceiling fan spins with the fan speed;
- a person appears when the room is occupied;
- a thermometer and a humidity dial show the readings.

Press **Play** and watch the thermostat flick on and off while the fuzzy rooms glide.

### 7.9 Checks and reports
- **44 automated tests** (`python -m pytest`) check everything above, from the worked
  example to the eco mode never heating a room in summer.
- **One-click PDF report**, from the dashboard or from `python main.py`
  (`outputs/report.pdf`).

---

## 8. Project files and how to use them

| File | What it does |
|---|---|
| `fuzzy_controller.py` | The original "brain": labels, rules and the four steps |
| `fuzzy_pi.py` | The smarter Fuzzy PI brain |
| `simulation.py` | The fake room, the thermostat, the 24-hour day, eco mode, noise and the scoring |
| `visualize.py` | Draws all the graphs |
| `room_view.py` | The animated Live Room |
| `report_pdf.py` | Builds the PDF reports |
| `main.py` | Runs everything and prints the result tables |
| `app.py` | The interactive web dashboard |
| `hardware/` | The ESP32 version and the table exporter |
| `tests/` | The 44 automated checks |
| `report.md` | The full academic report |
| `outputs/` | All saved graphs, tables and `report.pdf` |

**Run it:**

```bash
cd project
pip install -r requirements.txt
python main.py                                  # tables, graphs, PDF report, ESP32 table
streamlit run app.py --server.port 6000         # dashboard at http://localhost:6000
python -m pytest                                # run the 44 automated checks
```

**In the dashboard:**
- **Controller:** move the sliders to see which rules fire, the room picture and the
  output.
- **Live Room:** press Play to watch the rooms side by side.
- **Simulation:** pick a day, the controllers, noise or eco mode in the sidebar, then
  read the graphs and the scorecard.
- **Rule & MF Editor:** change the rules and shapes and see what happens.
- **Reports & Downloads:** get the PDF, the CSV data and the ESP32 table.

---

## Glossary

| Term | Meaning |
|---|---|
| Fuzzy logic | Reasoning with degrees of truth (0 to 1) instead of just yes/no |
| Membership function | The shape that says how much a value belongs to a word, e.g. how "hot" 26 °C is |
| Fuzzification | Turning a sensor number into word scores |
| Rule base | The list of IF–THEN rules |
| Firing strength | How strongly a rule applies right now (the weakest of its conditions) |
| Aggregation | Combining all the rules' votes into one shape |
| Defuzzification / centroid | Turning the combined shape back into one number by taking its balance point |
| Mamdani | The classic four-step recipe above (1975) |
| Hysteresis | The thermostat's dead band of ±1 °C, which stops it flickering on and off |
| Settling time | How long until the room enters the comfort zone and stays there |
| Steady-state error | How far from 23.5 °C the room sits once things calm down |
| Fuzzy PI | A fuzzy controller that nudges the AC power using the error and how fast it is changing |
| Integral action | Adding up small corrections over time until the error disappears |
| Eco dead band | The wider 20–27 °C band used while the room is empty |
| Lookup table (LUT) | Pre-calculated answers stored on the microcontroller |
