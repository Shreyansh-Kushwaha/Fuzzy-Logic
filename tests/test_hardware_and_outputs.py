"""Tests for the ESP32 lookup table, the PDF builder and the Live Room view."""

import json
import re

import numpy as np
import pytest

import export_lut
import fuzzy_controller as fc
import report_pdf
import room_view
import simulation as sim


@pytest.fixture(scope="module")
def tables():
    return export_lut.build_tables()


def test_lut_is_exact_on_grid_points(tables):
    ac_tab, fan_tab = tables
    for t, h in [(10, 20), (32, 75), (23.5, 50), (40, 90), (17, 33)]:
        ac, fan, _ = fc.compute(t, h)
        assert export_lut.lut_lookup(ac_tab, t, h) == pytest.approx(ac, abs=0.051)
        assert export_lut.lut_lookup(fan_tab, t, h) == pytest.approx(fan, abs=0.051)


def test_lut_interpolation_accuracy(tables):
    err = export_lut.lut_error(*tables, t_step=0.3, h_step=1.3)
    assert err["ac_mean"] < 0.15 and err["fan_mean"] < 0.1
    assert err["ac_max"] < 6.0 and err["fan_max"] < 3.0


def test_lut_clamps_out_of_range(tables):
    ac_tab, _ = tables
    assert export_lut.lut_lookup(ac_tab, 55, 99) == export_lut.lut_lookup(ac_tab, 40, 90)


def test_header_file(tmp_path, tables):
    path = export_lut.write_header(*tables, str(tmp_path / "fuzzy_lut.h"))
    text = open(path, encoding="utf-8").read()
    assert f"#define LUT_T_N    {export_lut.T_N}" in text
    assert f"#define LUT_H_N    {export_lut.H_N}" in text
    rows = re.findall(r"^  \{(.+)\},$", text, flags=re.M)
    assert len(rows) == 2 * export_lut.H_N
    assert all(len(r.split(",")) == export_lut.T_N for r in rows)


def test_pdf_builder_returns_pdf(tmp_path):
    rows = sim.metrics_rows(sim.run_scenario(sim.SCENARIOS["C"]))
    import visualize as viz
    data = report_pdf.build_pdf([
        ("text", "Summary", ["One paragraph.", "- a bullet"]),
        ("table", "Metrics", rows),
        ("figure", "Membership", viz.plot_membership("temperature")),
    ])
    assert data[:5] == b"%PDF-" and len(data) > 5000
    out = tmp_path / "r.pdf"
    report_pdf.build_pdf([("text", "x", ["y"])], str(out))
    assert out.read_bytes()[:5] == b"%PDF-"


def _payload(html):
    return json.loads(re.search(r"const D = (\{.*?\});\n", html, flags=re.S).group(1))


def test_room_view_payload():
    results = sim.run_scenario(sim.SCENARIOS["A"])
    d = _payload(room_view.room_html(results))
    assert d["n"] == 120 and d["animate"] is True
    assert [r["name"] for r in d["rooms"]] == [r.controller for r in results]
    for r in d["rooms"]:
        assert len(r["T"]) == 121 and len(r["ac"]) == 120 and len(r["kwh"]) == 121
        assert r["kwh"][-1] == pytest.approx(
            [x for x in results if x.controller == r["name"]][0].metrics["kwh"], abs=0.002)


def test_static_room_view():
    d = _payload(room_view.static_room_html(14, 40, -72.4, 18.4))
    assert d["animate"] is False and d["n"] == 1
    assert d["rooms"][0]["ac"] == [-72.4]
