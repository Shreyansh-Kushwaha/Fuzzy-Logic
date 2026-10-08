"""Tests for the hardware LUT, the PDF builder and the room view."""
import json
import re

import numpy as np

import export_lut
import report_pdf
import room_view
import simulation as sim


def test_lut_accuracy(tmp_path):
    ac, fan = export_lut.build_tables()
    assert ac.shape == (export_lut.H_N, export_lut.T_N)
    assert export_lut.lut_lookup(ac, 32, 75) == np.round(76.6667, 1)
    err = export_lut.lut_error(ac, fan, t_step=0.3, h_step=1.5)
    assert err["ac_mean"] < 0.2 and err["ac_max"] < 6 and err["fan_max"] < 3
    text = open(export_lut.write_header(ac, fan, str(tmp_path / "lut.h"))).read()
    assert "#define LUT_T_N    61" in text and text.count("{") == 2 + 2 * export_lut.H_N


def test_pdf_builds():
    pdf = report_pdf.build_pdf([("text", "Hello", ["- one", "two"]), ("table", "T", [{"a": 1, "b": "x"}])])
    assert pdf[:4] == b"%PDF"


def test_room_view_payload():
    html = room_view.room_html(sim.run_scenario(sim.SCENARIOS["A"]))
    data = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1))
    assert data["n"] == 120 and len(data["rooms"]) == 3 and len(data["rooms"][0]["T"]) == 121
    assert "Empty" in room_view.static_room_html(30, 70, 40, 50)
