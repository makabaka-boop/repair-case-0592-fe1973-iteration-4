"""双探头保守复核接口测试：下包络结果、按探头定位的 422、旧接口兼容。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def dual_payload(points_a, points_b) -> dict:
    return {"probeA": {"points": points_a}, "probeB": {"points": points_b}}


def p(time, temperature) -> dict:
    return {"time": time, "temperature": temperature}


def post_dual(payload: dict):
    return client.post("/api/lethality/dual", json=payload)


def post_dual_raw(raw: str):
    return client.post(
        "/api/lethality/dual",
        content=raw,
        headers={"Content-Type": "application/json"},
    )


def errors_of(response) -> list[dict]:
    assert response.status_code == 422, response.text
    return response.json()["detail"]["errors"]


def has_error(errors, row, field, probe=None) -> bool:
    return any(
        e["row"] == row and e["field"] == field and e.get("probe") == probe
        for e in errors
    )


CONST_121 = [p(t, 121.1) for t in (0, 60, 120, 180)]


class TestDualHappyPath:
    def test_identical_probes_equal_single_probe_result(self):
        body = post_dual(dual_payload(CONST_121, CONST_121)).json()
        assert body["passed"] is True
        assert body["threshold"] == pytest.approx(3.0)
        assert body["conservativeUnrounded"] == pytest.approx(3.0)
        assert body["conservativeF0"] == pytest.approx(3.0)
        assert body["probeATotalUnrounded"] == pytest.approx(3.0)
        assert body["probeBTotalUnrounded"] == pytest.approx(3.0)
        assert body["shortfall"] is None
        # 两线完全重合：每个并集段都标 both
        assert len(body["segments"]) == 3
        assert all(s["source"] == "both" for s in body["segments"])
        assert all(
            s["probeAStartRate"] == pytest.approx(1.0)
            and s["probeBStartRate"] == pytest.approx(1.0)
            for s in body["segments"]
        )

    def test_different_grids_and_internal_crossing(self):
        # A: 1→3；B: 3→1，交点 t=30，rate=2（温度由速率反推）
        import math

        def temp(rate):
            return 121.1 + 10 * math.log10(rate)

        payload = dual_payload(
            [p(0, temp(1.0)), p(30, temp(2.0)), p(60, temp(3.0))],
            [p(0, temp(3.0)), p(60, temp(1.0))],
        )
        body = post_dual(payload).json()
        # 保守总量仅 1.5 min，不达标；这里只验证拆段与曲线结构
        assert body["passed"] is False
        assert body["conservativeUnrounded"] == pytest.approx(1.5)
        sources = [s["source"] for s in body["segments"]]
        assert sources == ["probeA", "probeB"]
        assert body["segments"][0]["endTime"] == pytest.approx(30.0)
        # 曲线数据回传，供页面表格与图形共用同一响应
        assert body["probeA"]["points"][1]["rate"] == pytest.approx(2.0)
        assert body["probeB"]["points"][0]["rate"] == pytest.approx(3.0)

    def test_failing_conservative_batch_reports_unrounded_shortfall(self):
        # 两支探头都是 121.1 °C 恒温 179 s：保守总量 = 179/60 = 2.98333…
        points = [p(t, 121.1) for t in (0, 60, 120, 179)]
        body = post_dual(dual_payload(points, points)).json()
        assert body["passed"] is False
        assert body["conservativeUnrounded"] == pytest.approx(179 / 60)
        assert body["shortfall"] == pytest.approx(3.0 - 179 / 60)

    def test_conservative_total_is_below_min_of_two_totals(self):
        # 两支探头各有一段“更冷”：下包络严格小于两者总量
        import math

        def temp(rate):
            return 121.1 + 10 * math.log10(rate)

        payload = dual_payload(
            [p(0, temp(1.0)), p(60, temp(3.0))],
            [p(0, temp(3.0)), p(60, temp(1.0))],
        )
        body = post_dual(payload).json()
        assert body["conservativeUnrounded"] == pytest.approx(1.5)
        assert body["probeATotalUnrounded"] == pytest.approx(2.0)
        assert body["probeBTotalUnrounded"] == pytest.approx(2.0)

    def test_segment_contributions_sum_to_conservative_total(self):
        payload = dual_payload(
            [p(0, 120.0), p(30, 126.0), p(60, 118.0)],
            [p(0, 122.0), p(45, 119.0), p(60, 127.0)],
        )
        body = post_dual(payload).json()
        assert sum(s["contribution"] for s in body["segments"]) == pytest.approx(
            body["conservativeUnrounded"]
        )


class TestDualValidation:
    def test_each_probe_validated_independently_with_probe_tag(self):
        payload = dual_payload(
            [p(0, 99.0), p(60, 121.1)],  # probeA 第 1 行温度越界
            CONST_121,
        )
        errors = errors_of(post_dual(payload))
        assert has_error(errors, 1, "temperature", "probeA")
        assert not any(e.get("probe") == "probeB" for e in errors)

    def test_errors_from_both_probes_reported_together(self):
        payload = dual_payload(
            [p(0, 121.1), p(61, 121.1)],  # probeA 第 2 行超间隔
            [p(0, 121.1), p(30, 141.0)],  # probeB 第 2 行温度越界
        )
        errors = errors_of(post_dual(payload))
        assert has_error(errors, 2, "time", "probeA")
        assert has_error(errors, 2, "temperature", "probeB")

    def test_probe_must_be_object(self):
        response = post_dual({"probeA": [1, 2], "probeB": {"points": CONST_121}})
        errors = errors_of(response)
        assert has_error(errors, None, "probeA", "probeA")

    def test_whole_body_must_be_object(self):
        errors = errors_of(post_dual_raw("[1, 2]"))
        assert has_error(errors, None, "body")

    def test_invalid_json_rejected(self):
        errors = errors_of(post_dual_raw("{not json"))
        assert has_error(errors, None, "body")

    def test_first_sample_of_each_probe_must_start_at_zero(self):
        payload = dual_payload(
            [p(5, 121.1), p(60, 121.1)],
            [p(0, 121.1), p(60, 121.1)],
        )
        errors = errors_of(post_dual(payload))
        assert has_error(errors, 1, "time", "probeA")
        assert not any(e.get("probe") == "probeB" for e in errors)

    def test_interval_rule_applies_per_probe(self):
        payload = dual_payload(
            CONST_121,
            [p(0, 121.1), p(61, 121.1)],
        )
        errors = errors_of(post_dual(payload))
        assert has_error(errors, 2, "time", "probeB")

    def test_single_point_probe_rejected(self):
        payload = dual_payload([p(0, 121.1)], CONST_121)
        errors = errors_of(post_dual(payload))
        # 单点探头本身报“至少需要 2 个采样点”，且因时间序列不可用
        # 无法比较结束时刻（不叠加跨探头误报）
        assert has_error(errors, None, "points", "probeA")
        assert not any(e["field"] == "probe" for e in errors)

    def test_end_seconds_must_match(self):
        payload = dual_payload(
            [p(0, 121.1), p(60, 121.1), p(120, 121.1)],
            [p(0, 121.1), p(60, 121.1)],
        )
        errors = errors_of(post_dual(payload))
        mismatch = [e for e in errors if e["field"] == "probe" and e["row"] is None]
        assert mismatch, errors
        assert "同一秒" in mismatch[0]["message"]
        assert "120" in mismatch[0]["message"]
        assert "60" in mismatch[0]["message"]

    def test_end_mismatch_not_reported_when_times_are_invalid(self):
        # probeA 时间非法时不再叠加“结束时刻不一致”，避免级联误报
        payload = dual_payload(
            [p(0, 121.1), p(60, 121.1), p(40, 121.1)],
            [p(0, 121.1), p(30, 121.1)],
        )
        errors = errors_of(post_dual(payload))
        assert has_error(errors, 3, "time", "probeA")
        assert not any(e["field"] == "probe" for e in errors)

    def test_failed_request_returns_no_conservative_result(self):
        payload = dual_payload([p(0, 99.0), p(60, 121.1)], CONST_121)
        body = post_dual(payload).json()
        assert "conservativeUnrounded" not in body
        assert "segments" not in body


class TestSingleProbeEndpointUnchanged:
    """原接口及其响应保持兼容（响应不得出现双探头字段）。"""

    def test_single_endpoint_response_shape_unchanged(self):
        response = client.post(
            "/api/lethality", json={"points": CONST_121}
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {
            "f0",
            "threshold",
            "passed",
            "shortfall",
            "segments",
        }
        assert body["f0"] == pytest.approx(3.0)
        assert "probe" not in body["segments"][0]

    def test_single_endpoint_validation_issues_have_no_probe_field_value(self):
        response = client.post(
            "/api/lethality",
            json={"points": [p(0, 121.1), p(30, 99.0)]},
        )
        errors = errors_of(response)
        assert has_error(errors, 2, "temperature")  # probe 为 None
