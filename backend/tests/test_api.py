"""API 联调测试：合法请求的计算结果与各类非法行的 422 定位。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def valid_payload() -> dict:
    return {
        "points": [
            {"time": 0, "temperature": 121.1},
            {"time": 60, "temperature": 121.1},
            {"time": 120, "temperature": 121.1},
            {"time": 180, "temperature": 121.1},
        ]
    }


def post(payload: dict):
    return client.post("/api/lethality", json=payload)


def errors_of(response) -> list[dict]:
    assert response.status_code == 422, response.text
    return response.json()["detail"]["errors"]


def has_error(errors: list[dict], row, field) -> bool:
    return any(e["row"] == row and e["field"] == field for e in errors)


class TestHealth:
    def test_health(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestHappyPath:
    def test_passing_batch(self):
        response = post(valid_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["passed"] is True
        assert body["f0"] == pytest.approx(3.0)
        assert body["threshold"] == pytest.approx(3.0)
        assert body["shortfall"] is None
        assert len(body["segments"]) == 3
        first = body["segments"][0]
        assert first["index"] == 1
        assert first["startTime"] == 0
        assert first["endTime"] == 60
        assert first["durationSeconds"] == 60
        assert first["contribution"] == pytest.approx(1.0)

    def test_failing_batch_reports_gap_to_threshold(self):
        payload = valid_payload()
        payload["points"][-1]["time"] = 179
        body = post(payload).json()
        assert body["passed"] is False
        assert body["f0"] == pytest.approx(2.98)
        assert body["shortfall"] == pytest.approx(0.02)

    def test_temperature_boundaries_are_inclusive(self):
        payload = {
            "points": [
                {"time": 0, "temperature": 100.0},
                {"time": 60, "temperature": 140.0},
            ]
        }
        assert post(payload).status_code == 200

    def test_integer_temperature_accepted(self):
        payload = {
            "points": [
                {"time": 0, "temperature": 121},
                {"time": 30, "temperature": 122},
            ]
        }
        assert post(payload).status_code == 200

    def test_segment_contributions_are_unrounded_and_reproduce_total(self):
        # 100 °C 下每段 30 s 贡献约 0.00388 min：接口若提前保留两位小数
        # 会变成 0.0，质检员无法据分段复算合计。段贡献须为未舍入值。
        payload = {
            "points": [
                {"time": 0, "temperature": 100.0},
                {"time": 30, "temperature": 100.0},
                {"time": 60, "temperature": 100.0},
            ]
        }
        body = post(payload).json()
        contributions = [s["contribution"] for s in body["segments"]]
        assert contributions == pytest.approx([0.00388123558, 0.00388123558], abs=1e-9)
        # 各段未舍入之和即未舍入合计，最终 F₀ 再整体四舍五入为 0.01
        assert sum(contributions) == pytest.approx(0.00776247117, abs=1e-9)
        assert body["f0"] == pytest.approx(0.01)

    def test_heating_ramp_segment_uses_trapezoid_average(self):
        payload = {
            "points": [
                {"time": 0, "temperature": 100.0},
                {"time": 60, "temperature": 140.0},
            ]
        }
        body = post(payload).json()
        assert body["segments"][0]["contribution"] == pytest.approx(
            38.8162365, abs=1e-6
        )
        assert body["passed"] is True

    def test_rounded_threshold_is_release_boundary(self):
        # 未舍入 total 略低于 3.0，但 F₀ 四舍五入为 3.00：判放行、无差额
        payload = {
            "points": [
                {"time": 0, "temperature": 125.865},
                {"time": 60, "temperature": 125.865},
            ]
        }
        body = post(payload).json()
        assert body["f0"] == pytest.approx(3.0)
        assert body["passed"] is True
        assert body["shortfall"] is None


class TestValidationFailures:
    def test_single_point_rejected(self):
        errors = errors_of(post({"points": [{"time": 0, "temperature": 121.1}]}))
        assert has_error(errors, None, "points")

    def test_empty_points_rejected(self):
        errors = errors_of(post({"points": []}))
        assert has_error(errors, None, "points")

    def test_first_time_must_be_zero(self):
        payload = valid_payload()
        payload["points"][0]["time"] = 5
        errors = errors_of(post(payload))
        assert has_error(errors, 1, "time")

    def test_time_must_be_integer_seconds(self):
        payload = valid_payload()
        payload["points"][1]["time"] = 30.5
        errors = errors_of(post(payload))
        assert has_error(errors, 2, "time")

    def test_boolean_time_rejected(self):
        payload = valid_payload()
        payload["points"][1]["time"] = True
        errors = errors_of(post(payload))
        assert has_error(errors, 2, "time")

    def test_times_must_be_strictly_increasing(self):
        payload = valid_payload()
        payload["points"][2]["time"] = 60  # 与前一点相同
        errors = errors_of(post(payload))
        assert has_error(errors, 3, "time")

    def test_interval_over_60_seconds_rejected(self):
        payload = valid_payload()
        payload["points"][1]["time"] = 61
        errors = errors_of(post(payload))
        assert has_error(errors, 2, "time")

    def test_interval_of_exactly_60_seconds_accepted(self):
        assert post(valid_payload()).status_code == 200

    @pytest.mark.parametrize("temperature", [99.9, 140.1])
    def test_temperature_out_of_range_rejected(self, temperature):
        payload = valid_payload()
        payload["points"][1]["temperature"] = temperature
        errors = errors_of(post(payload))
        assert has_error(errors, 2, "temperature")

    def test_temperature_must_be_finite(self):
        # Python 的 json 解析默认接受 NaN/Infinity，必须显式拒绝
        response = client.post(
            "/api/lethality",
            content='{"points": [{"time": 0, "temperature": NaN},'
            ' {"time": 30, "temperature": 121.1}]}',
            headers={"Content-Type": "application/json"},
        )
        errors = errors_of(response)
        assert has_error(errors, 1, "temperature")

    def test_missing_temperature_rejected(self):
        payload = valid_payload()
        del payload["points"][2]["temperature"]
        errors = errors_of(post(payload))
        assert has_error(errors, 3, "temperature")

    def test_null_time_rejected(self):
        payload = valid_payload()
        payload["points"][0]["time"] = None
        errors = errors_of(post(payload))
        assert has_error(errors, 1, "time")

    def test_multiple_invalid_rows_all_reported(self):
        payload = valid_payload()
        payload["points"][1]["temperature"] = 99.0
        payload["points"][3]["time"] = 999
        errors = errors_of(post(payload))
        assert has_error(errors, 2, "temperature")
        assert has_error(errors, 4, "time")

    def test_failed_request_returns_no_result(self):
        payload = valid_payload()
        payload["points"][1]["temperature"] = 99.0
        body = post(payload).json()
        assert "f0" not in body
        assert "segments" not in body

    def test_non_object_body_rejected(self):
        response = client.post(
            "/api/lethality",
            content="[1, 2, 3]",
            headers={"Content-Type": "application/json"},
        )
        errors = errors_of(response)
        assert has_error(errors, None, "points")

    def test_invalid_json_rejected(self):
        response = client.post(
            "/api/lethality",
            content="{not json",
            headers={"Content-Type": "application/json"},
        )
        errors = errors_of(response)
        assert has_error(errors, None, "body")
