"""Tests for the Mamdani FIS."""
import math

import numpy as np
import pytest
import skfuzzy as fuzz

import fuzzy_controller as fc


def test_worked_example_matches_hand_calculation():
    ac, fan, w = fc.compute(32, 75)
    assert ac == pytest.approx(76.6667, abs=1e-3)      # centroid of strong_cool
    assert fan == pytest.approx(84.4444, abs=1e-3)     # centroid of fan high
    assert list(np.nonzero(w)[0]) == [8] and w[8] == 1.0  # only rule 9 fires


@pytest.mark.parametrize("t, expected", [
    (20, {"cold": 1 / 3, "comfortable": 0.4, "hot": 0.0}),
    (26, {"cold": 0.0, "comfortable": 0.4, "hot": 1 / 3}),
    (23, {"cold": 0.0, "comfortable": 1.0, "hot": 0.0}),
])
def test_temperature_fuzzification(t, expected):
    got = fc.infer(t, 50).temp_degrees
    for term, mu in expected.items():
        assert got[term] == pytest.approx(mu, abs=1e-9)


def test_humidity_fuzzification():
    got = fc.infer(23, 40).hum_degrees
    assert got["low"] == pytest.approx(1 / 3) and got["medium"] == pytest.approx(1 / 3) and got["high"] == 0


@pytest.mark.parametrize("t, h", [(-50, 0), (100, 150), (math.inf, -math.inf), (math.nan, 50), (None, "abc")])
def test_edge_inputs_never_raise(t, h):
    ac, fan, w = fc.compute(t, h)
    assert -100 <= ac <= 100 and 0 <= fan <= 100 and w.sum() > 0


def test_some_rule_fires_everywhere_and_outputs_in_range():
    for t in np.arange(10, 40.01, 0.5):
        for h in np.arange(20, 90.01, 2.5):
            ac, fan, w = fc.compute(t, h)
            assert w.max() > 0
            assert -76.67 - 1e-6 <= ac <= 76.67 + 1e-6 and 0 <= fan <= 100


@pytest.mark.parametrize("h", [25, 50, 75])
def test_more_heat_never_means_less_cooling(h):
    temps = np.arange(10, 40.01, 0.25)
    ac, _ = fc.compute_many(temps, np.full_like(temps, h))
    assert np.all(np.diff(ac) >= -1e-9)


def test_vectorised_matches_step_by_step():
    T, H = np.meshgrid(np.arange(10, 40.01, 1.5), np.arange(20, 90.01, 3.5))
    ac, fan = fc.compute_many(T, H)
    ref = np.array([[fc.compute(a, b)[:2] for a, b in zip(r1, r2)] for r1, r2 in zip(T, H)])
    assert np.abs(ref[..., 0] - ac).max() < 1e-9 and np.abs(ref[..., 1] - fan).max() < 1e-9


def test_centroid_many_matches_skfuzzy():
    u = fc.ac_universe
    sets = np.vstack([np.fmin(0.4, fc.ac_mfs["mild_cool"]),
                      np.fmax(np.fmin(0.7, fc.ac_mfs["off"]), np.fmin(0.2, fc.ac_mfs["strong_heat"]))])
    got = fc.centroid_many(u, sets, 0.0)
    for row, value in zip(sets, got):
        assert value == pytest.approx(fuzz.defuzz(u, row, "centroid"), abs=1e-9)


def test_agrees_with_skfuzzy_control():
    sim = fc.build_skfuzzy_ctrl()
    for t, h in [(14, 40), (26, 60), (25.5, 62), (12, 85)]:
        sim.input["temperature"], sim.input["humidity"] = t, h
        sim.compute()
        ac, fan, _ = fc.compute(t, h)
        assert ac == pytest.approx(sim.output["ac_power"], abs=1e-3)
        assert fan == pytest.approx(sim.output["fan_speed"], abs=1e-3)


def test_validate_mf_defs():
    assert fc.validate_mf_defs(fc.TEMP_MF_DEFS, *fc.TEMP_RANGE) == []
    bad = {"x": ("trimf", [20, 15, 25]), "y": ("trapmf", [5, 10, 20, 30]), "z": ("trimf", [1, 2])}
    assert len(fc.validate_mf_defs(bad, *fc.TEMP_RANGE)) == 3


def test_edited_rules_change_the_output():
    rules = [r if r[0] != 9 else (9, "hot", "high", "off", "low") for r in fc.RULES]
    ac, fan, _ = fc.RoomFIS(rules=rules).compute(32, 75)
    assert abs(ac) < 1e-6 and fan < 20


def test_mode_label():
    assert [fc.mode_label(v) for v in (-50, 0, 3, 50)] == ["Heating", "Idle", "Idle", "Cooling"]
