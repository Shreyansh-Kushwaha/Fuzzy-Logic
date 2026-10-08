"""Tests for the improved Fuzzy PI controller."""
import pytest

import fuzzy_pi as fp
import simulation as sim

NEG = {"NB": "PB", "NS": "PS", "ZE": "ZE", "PS": "NS", "PB": "NB", "N": "P", "Z": "Z", "P": "N"}


def test_rule_table_is_antisymmetric():
    for e, row in fp.PI_RULE_TABLE.items():
        for d, out in row.items():
            assert fp.PI_RULE_TABLE[NEG[e]][NEG[d]] == NEG[out]


def test_no_change_at_setpoint():
    assert fp.PI_FIS.infer(error=0, d_error=0).crisp["du"] == pytest.approx(0, abs=1e-9)


def test_humidity_setpoint():
    assert fp.humidity_setpoint(30) == pytest.approx(23.5)
    assert fp.humidity_setpoint(80) == pytest.approx(23.5 - fp.HUMIDITY_SETPOINT_SHIFT)


@pytest.mark.parametrize("key", ["A", "B", "C"])
def test_pi_removes_offset(key):
    r = sim.simulate(fp.FuzzyPIController(), sim.SCENARIOS[key])
    assert sim.COMFORT_LOW <= r.metrics["final_T_C"] <= sim.COMFORT_HIGH
    assert r.metrics["settling_time_min"] is not None
    assert r.metrics["steady_state_error_C"] < 0.5
    assert r.metrics["switching_events"] <= 3


def test_reset_clears_state():
    c = fp.FuzzyPIController()
    c(30, 50)
    c.reset()
    assert c.u == 0 and c.prev_error is None and c.T_filtered is None
