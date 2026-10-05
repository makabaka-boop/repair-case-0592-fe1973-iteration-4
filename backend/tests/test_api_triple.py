"""三探头中位复核接口测试。"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def p(time, temperature):
    return {"time": time, "temperature": temperature}


def temp(rate):
    return 121.1 + 10.0 * math.log10(rate)


def triple_payload(a, b, c):
    return {"probeA": {"points": a}, "probeB": {"points": b}, "probeC": {"points": c}}


def post(payload):
    return client.post("/api/lethality/triple", json=payload)


def post_raw(raw):
    return client.post(
        "/api/lethality/triple",
        content=raw,
        headers={"Content-Type": "application/json"},
    )


def errors_of(response):
    assert response.status_code == 422, response.text
    return response.json()["detail"]["errors"]


def has_error(errors, row, field, probe=None):
    return any(
        e["row"] == row
        and e["field"] == field
        and e.get("probe") == probe
        for e in errors
    )


CONST_121 = [p(t, 121.1) for t in (0, 60, 120, 180)]


class TestTripleApi:
    def test_identical_three_probes_returns_shared_boundaries_and_passes(self):
        response = post(triple_payload(CONST_121, CONST_121, CONST_121))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mode"] == "triple"
        assert body["medianUnrounded"] == pytest.approx(3.0)
        assert body["medianF0"] == pytest.approx(3.0)
        assert body["passed"] is True
        assert body["shortfall"] is None
        assert [b["time"] for b in body["boundaries"]] == [0, 60, 120, 180]
        assert len(body["segments"]) == 3
        assert all(s["source"] == "probeA" for s in body["segments"])
        for index, segment in enumerate(body["segments"], start=1):
            assert segment["startBoundaryIndex"] == index
            assert segment["endBoundaryIndex"] == index + 1
            assert segment["startTime"] == body["boundaries"][index - 1]["time"]
            assert segment["endTime"] == body["boundaries"][index]["time"]
        assert all("三条曲线并列中位" in s["sourceReason"] for s in body["segments"])

    def test_internal_median_switch_and_graph_table_fields_share_boundaries(self):
        a = [p(0, temp(1)), p(60, temp(5))]
        b = [p(0, temp(5)), p(60, temp(1))]
        c = [p(0, temp(2)), p(30, temp(4)), p(60, temp(2))]
        body = post(triple_payload(a, b, c)).json()

        assert [bnd["time"] for bnd in body["boundaries"]] == pytest.approx(
            [0, 22.5, 30, 37.5, 60]
        )
        assert [s["source"] for s in body["segments"]] == [
            "probeC",
            "probeB",
            "probeA",
            "probeC",
        ]
        assert body["medianUnrounded"] == pytest.approx(2.875)
        assert sum(s["contribution"] for s in body["segments"]) == pytest.approx(
            body["medianUnrounded"]
        )
        node = body["boundaries"][2]
        assert node["type"] == "sample"
        assert node["crossingPairs"] == [["probeA", "probeB"]]
        assert "探头A/探头B" in node["reason"]
        assert node["medianReason"]

    def test_threshold_uses_unrounded_median(self):
        rate = temp(2.99996 / 3.0)
        points = [p(t, rate) for t in (0, 60, 120, 180)]
        body = post(triple_payload(points, points, points)).json()
        assert body["medianUnrounded"] == pytest.approx(2.99996)
        assert body["medianF0"] == pytest.approx(3.0)
        assert body["passed"] is False
        assert body["shortfall"] == pytest.approx(0.00004)

    def test_missing_probe_c_rejected(self):
        response = client.post(
            "/api/lethality/triple",
            json={"probeA": {"points": CONST_121}, "probeB": {"points": CONST_121}},
        )
        errors = errors_of(response)
        assert has_error(errors, None, "probeC", "probeC")

    def test_probe_c_row_error_tagged(self):
        bad_c = [p(0, 121.1), p(61, 121.1)]
        errors = errors_of(post(triple_payload(CONST_121, CONST_121, bad_c)))
        assert has_error(errors, 2, "time", "probeC")

    def test_non_overlapping_end_time_domain_rejected_as_whole_analysis(self):
        c = [p(t, 121.1) for t in (0, 60, 120, 179)]
        errors = errors_of(post(triple_payload(CONST_121, CONST_121, c)))
        cross = [e for e in errors if e["field"] == "probe" and e["row"] is None]
        assert cross
        assert "共同时间域" in cross[0]["message"]
        assert "180" in cross[0]["message"]
        assert "179" in cross[0]["message"]

    def test_non_object_body_and_invalid_json_rejected(self):
        assert has_error(errors_of(post_raw("[1]")), None, "body")
        assert has_error(errors_of(post_raw("{bad")), None, "body")

    def test_invalid_response_has_no_result(self):
        response = post(triple_payload(CONST_121, CONST_121, []))
        assert "medianUnrounded" not in response.json()
        assert "segments" not in response.json()


class TestOlderEndpointsUnchanged:
    def test_dual_response_does_not_gain_triple_fields(self):
        response = client.post(
            "/api/lethality/dual",
            json={
                "probeA": {"points": CONST_121},
                "probeB": {"points": CONST_121},
            },
        )
        body = response.json()
        assert "probeC" not in body
        assert "medianUnrounded" not in body
        assert "boundaries" not in body
        assert body["conservativeUnrounded"] == pytest.approx(3.0)

    def test_single_response_unchanged(self):
        body = client.post("/api/lethality", json={"points": CONST_121}).json()
        assert set(body) == {"f0", "threshold", "passed", "shortfall", "segments"}
