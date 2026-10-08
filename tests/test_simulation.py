"""Tests for the room model, the thermostat, the experiments and the metrics."""
import numpy as np
import pytest

import simulation as sim


def test_room_step_signs():
    T, H = sim.room_step(25, 60, 100, 25, 60)
    assert T == pytest.approx(24.5) and H == pytest.approx(59.7)
    T, H = sim.room_step(20, 60, -100, 20, 60)
    assert T == pytest.approx(20.5) and H == pytest.approx(60)
    assert sim.room_step(25, 20.1, 100, 25, 20)[1] == 20.0     # clamp


def test_onoff_hysteresis():
    c = sim.OnOffController()
    seq = [c(T, 50)[0] for T in (24.0, 24.6, 24.0, 23.5, 23.0, 22.4, 23.0, 23.5)]
    assert seq == [0, 100, 100, 0, 0, -100, -100, 0]


def test_metric_helpers():
    T = np.array([30, 27, 24, 23, 26, 24, 23.5])
    assert sim.settling_time(T) == 5
    assert sim.settling_time(np.array([24, 26])) is None
    assert sim.max_overshoot(np.array([30, 22.5, 23.5])) == pytest.approx(1.0)
    assert sim.switching_events(np.array([0, 50, 50, 0, -50, 2])) == 4
    assert sim.electrical_kwh(np.full(60, 100.0), np.zeros(60)) == pytest.approx(sim.AC_ELEC_KW)


def test_original_specification_numbers_are_reproduced():
    fz, _, oo = sim.run_scenario(sim.SCENARIOS["A"])
    assert fz.metrics["final_T_C"] == pytest.approx(25.24, abs=0.01)
    assert fz.metrics["energy"] == pytest.approx(6280.7, abs=0.1)
    assert oo.metrics["energy"] == pytest.approx(7300.0)
    assert oo.metrics["switching_events"] == 19


def test_noise_is_reproducible():
    a = sim.run_scenario(sim.SCENARIOS["C"], noise=True)
    b = sim.run_scenario(sim.SCENARIOS["C"], noise=True)
    c = sim.run_scenario(sim.SCENARIOS["C"])
    for x, y, z in zip(a, b, c):
        assert np.array_equal(x.T, y.T)
        assert not np.array_equal(x.T_measured, z.T_measured)


def test_daily_weather_shape():
    sc = sim.SCENARIOS["D"]
    assert sim.outside_conditions(sc, 15 * 60)[0] == pytest.approx(sc.T_outside + sc.T_amp)
    assert sim.outside_conditions(sc, 3 * 60)[0] == pytest.approx(sc.T_outside - sc.T_amp)


def test_occupancy_eco_mode():
    sc = sim.SCENARIOS["D"]
    always = sim.run_scenario(sc)
    eco = sim.run_scenario(sc, occupancy=True)
    for a, e in zip(always, eco):
        assert e.metrics["kwh"] < a.metrics["kwh"]                  # saves energy
        assert not np.any((e.ac < -sim.fc.MODE_THRESHOLD) & e.eco)  # never heats a summer eco room
    pi, onoff = eco[1], eco[2]
    assert pi.metrics["comfort_occupied_pct"] == 100 and onoff.metrics["comfort_occupied_pct"] == 100
