"""一次性验收服务：对运行中的 API 与 Web 做黑盒检查。

全部通过则以退出码 0 结束，否则以 1 结束。仅依赖标准库。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = os.environ.get("API_URL", "http://api:8000")
WEB_URL = os.environ.get("WEB_URL", "http://web")

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    suffix = f" — {detail}" if detail and not condition else ""
    print(f"[{status}] {name}{suffix}", flush=True)
    if not condition:
        failures.append(name)


def request(method: str, url: str, payload=None, raw: str | None = None):
    """返回 (status, parsed_body|None|raw_text)。"""
    data = None
    if raw is not None:
        data = raw.encode()
    elif payload is not None:
        data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode()
            try:
                return resp.status, json.loads(text)
            except json.JSONDecodeError:
                return resp.status, text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode()
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, text


def wait_ready(url: str, name: str, attempts: int = 60) -> bool:
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status < 500:
                    print(f"[ OK ] {name} 就绪", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(2)
    print(f"[FAIL] {name} 未就绪: {url}", flush=True)
    return False


def has_error(errors, row, field) -> bool:
    return any(e.get("row") == row and e.get("field") == field for e in errors)


def main() -> int:
    ready = wait_ready(f"{API_URL}/api/health", "API") & wait_ready(f"{WEB_URL}/", "Web")
    if not ready:
        return 1

    passing = {"points": [{"time": t, "temperature": 121.1} for t in (0, 60, 120, 180)]}
    failing = {"points": [{"time": t, "temperature": 121.1} for t in (0, 60, 120, 179)]}

    # 1. 健康检查
    status, body = request("GET", f"{API_URL}/api/health")
    check("API 健康检查", status == 200 and body == {"status": "ok"}, f"{status} {body}")

    # 2. 达标批次：121.1 °C 恒温 180 s → F₀ = 3.00，放行
    status, body = request("POST", f"{API_URL}/api/lethality", passing)
    ok = (
        status == 200
        and body.get("passed") is True
        and abs(body.get("f0", 0) - 3.0) < 1e-9
        and body.get("shortfall") is None
        and len(body.get("segments", [])) == 3
        and all(abs(s.get("contribution", 0) - 1.0) < 1e-9 for s in body["segments"])
    )
    check("达标批次 F₀=3.00 放行且逐段贡献正确", ok, f"{status} {body}")

    # 3. 不足量批次：179 s → F₀ = 2.98，差额 0.02
    status, body = request("POST", f"{API_URL}/api/lethality", failing)
    ok = (
        status == 200
        and body.get("passed") is False
        and abs(body.get("f0", 0) - 2.98) < 1e-9
        and abs(body.get("shortfall", 0) - 0.02) < 1e-9
    )
    check("不足量批次 F₀=2.98 且差额 0.02", ok, f"{status} {body}")

    # 4. 单采样点拒绝
    status, body = request(
        "POST", f"{API_URL}/api/lethality", {"points": [{"time": 0, "temperature": 121.1}]}
    )
    errors = (body or {}).get("detail", {}).get("errors", [])
    check(
        "单采样点返回 422 并指向 points",
        status == 422 and has_error(errors, None, "points"),
        f"{status} {body}",
    )

    # 5. 温度越界定位到行与字段
    bad_temp = {"points": [{"time": 0, "temperature": 121.1}, {"time": 30, "temperature": 99.9}]}
    status, body = request("POST", f"{API_URL}/api/lethality", bad_temp)
    errors = (body or {}).get("detail", {}).get("errors", [])
    check(
        "温度 99.9 °C 返回 422 并定位第 2 行 temperature",
        status == 422 and has_error(errors, 2, "temperature"),
        f"{status} {body}",
    )

    # 6. 间隔超过 60 秒
    bad_gap = {"points": [{"time": 0, "temperature": 121.1}, {"time": 61, "temperature": 121.1}]}
    status, body = request("POST", f"{API_URL}/api/lethality", bad_gap)
    errors = (body or {}).get("detail", {}).get("errors", [])
    check(
        "间隔 61 秒返回 422 并定位第 2 行 time",
        status == 422 and has_error(errors, 2, "time"),
        f"{status} {body}",
    )

    # 7. 非整数秒
    bad_time = {"points": [{"time": 0, "temperature": 121.1}, {"time": 30.5, "temperature": 121.1}]}
    status, body = request("POST", f"{API_URL}/api/lethality", bad_time)
    errors = (body or {}).get("detail", {}).get("errors", [])
    check(
        "非整数秒返回 422 并定位第 2 行 time",
        status == 422 and has_error(errors, 2, "time"),
        f"{status} {body}",
    )

    # 8. 非有限温度（NaN）
    status, body = request(
        "POST",
        f"{API_URL}/api/lethality",
        raw='{"points": [{"time": 0, "temperature": NaN}, {"time": 30, "temperature": 121.1}]}',
    )
    errors = (body or {}).get("detail", {}).get("errors", []) if isinstance(body, dict) else []
    check(
        "NaN 温度返回 422 并定位第 1 行 temperature",
        status == 422 and has_error(errors, 1, "temperature"),
        f"{status} {body}",
    )

    # 9. Web 页面可访问
    status, body = request("GET", f"{WEB_URL}/")
    check(
        "Web 首页返回页面",
        status == 200 and isinstance(body, str) and '<div id="root">' in body,
        f"{status}",
    )

    # 10. 经 Web 同源代理调用 API（nginx → FastAPI 链路）
    status, body = request("POST", f"{WEB_URL}/api/lethality", passing)
    check(
        "经 Web 代理计算 F₀=3.00 放行",
        status == 200 and body.get("passed") is True and abs(body.get("f0", 0) - 3.0) < 1e-9,
        f"{status} {body}",
    )

    # 11. 双探头保守复核：相同探头 ⇒ 保守总量 3.00，各段 both
    dual_same = {"probeA": {"points": passing["points"]}, "probeB": {"points": passing["points"]}}
    status, body = request("POST", f"{API_URL}/api/lethality/dual", dual_same)
    ok = (
        status == 200
        and body.get("passed") is True
        and abs(body.get("conservativeUnrounded", 0) - 3.0) < 1e-9
        and len(body.get("segments", [])) == 3
        and all(s.get("source") == "both" for s in body.get("segments", []))
        and abs(body.get("probeATotalUnrounded", 0) - 3.0) < 1e-9
        and abs(body.get("probeBTotalUnrounded", 0) - 3.0) < 1e-9
    )
    check("双探头相同：保守 F₀=3.00、各段标 both、两探头总量一致", ok, f"{status} {body}")

    # 12. 双探头内部换源：A 1→3、B 3→1（速率），交点 t=30，保守总量 1.5，
    # 两段来源分别为 probeA、probeB；严格小于两探头各自的 2.0
    import math

    def temp_for_rate(rate: float) -> float:
        return 121.1 + 10.0 * math.log10(rate)

    dual_cross = {
        "probeA": {"points": [
            {"time": 0, "temperature": temp_for_rate(1.0)},
            {"time": 30, "temperature": temp_for_rate(2.0)},
            {"time": 60, "temperature": temp_for_rate(3.0)},
        ]},
        "probeB": {"points": [
            {"time": 0, "temperature": temp_for_rate(3.0)},
            {"time": 60, "temperature": temp_for_rate(1.0)},
        ]},
    }
    status, body = request("POST", f"{API_URL}/api/lethality/dual", dual_cross)
    segments = (body or {}).get("segments", []) if isinstance(body, dict) else []
    sources = [s.get("source") for s in segments]
    ok = (
        status == 200
        and sources == ["probeA", "probeB"]
        and len(segments) == 2
        and abs(segments[0].get("endTime", -1) - 30.0) < 1e-9
        and abs(body.get("conservativeUnrounded", 0) - 1.5) < 1e-9
        and body.get("conservativeUnrounded", 9) < body.get("probeATotalUnrounded", 0)
        and body.get("conservativeUnrounded", 9) < body.get("probeBTotalUnrounded", 0)
        and body.get("passed") is False  # 1.5 < 3.00
    )
    check(
        "双探头换源：交点拆段 probeA→probeB、保守总量 1.5 且非两总量较小值",
        ok,
        f"{status} {sources} {body if not ok else ''}",
    )

    # 13. 双探头校验：按探头定位行
    bad_dual = {
        "probeA": {"points": passing["points"]},
        "probeB": {"points": [
            {"time": 0, "temperature": 121.1},
            {"time": 61, "temperature": 121.1},
        ]},
    }
    status, body = request("POST", f"{API_URL}/api/lethality/dual", bad_dual)
    errors = (body or {}).get("detail", {}).get("errors", [])
    check(
        "双探头超间隔返回 422 并定位 probeB 第 2 行 time",
        status == 422
        and any(
            e.get("probe") == "probeB" and e.get("row") == 2 and e.get("field") == "time"
            for e in errors
        ),
        f"{status} {body}",
    )

    # 14. 双探头结束秒不一致
    end_mismatch = {
        "probeA": {"points": [
            {"time": 0, "temperature": 121.1},
            {"time": 60, "temperature": 121.1},
            {"time": 120, "temperature": 121.1},
        ]},
        "probeB": {"points": [
            {"time": 0, "temperature": 121.1},
            {"time": 60, "temperature": 121.1},
        ]},
    }
    status, body = request("POST", f"{API_URL}/api/lethality/dual", end_mismatch)
    errors = (body or {}).get("detail", {}).get("errors", [])
    check(
        "双探头结束秒不一致返回 422",
        status == 422 and any("同一秒" in e.get("message", "") for e in errors),
        f"{status} {body}",
    )

    # 15. 三探头中位复核：手算 A 1→5、B 5→1、C 2→4→2。
    # 共享边界为 0 / 22.5 / 30 / 37.5 / 60，来源 C→B→A→C，总量 2.875。
    triple_cross = {
        "probeA": {"points": [
            {"time": 0, "temperature": temp_for_rate(1.0)},
            {"time": 60, "temperature": temp_for_rate(5.0)},
        ]},
        "probeB": {"points": [
            {"time": 0, "temperature": temp_for_rate(5.0)},
            {"time": 60, "temperature": temp_for_rate(1.0)},
        ]},
        "probeC": {"points": [
            {"time": 0, "temperature": temp_for_rate(2.0)},
            {"time": 30, "temperature": temp_for_rate(4.0)},
            {"time": 60, "temperature": temp_for_rate(2.0)},
        ]},
    }
    status, body = request("POST", f"{API_URL}/api/lethality/triple", triple_cross)
    triple_segments = (body or {}).get("segments", []) if isinstance(body, dict) else []
    triple_boundaries = (body or {}).get("boundaries", []) if isinstance(body, dict) else []
    triple_sources = [s.get("source") for s in triple_segments]
    boundary_times = [b.get("time") for b in triple_boundaries]
    triple_ok = (
        status == 200
        and len(boundary_times) == 5
        and all(abs(actual - expected) < 1e-9 for actual, expected in zip(
            boundary_times, [0.0, 22.5, 30.0, 37.5, 60.0]
        ))
        and triple_sources == ["probeC", "probeB", "probeA", "probeC"]
        and abs(body.get("medianUnrounded", 0) - 2.875) < 1e-9
        and abs(body.get("medianF0", 0) - 2.88) < 1e-9
        and body.get("passed") is False
        and all(s.get("sourceReason") for s in triple_segments)
        and all(
            abs(triple_segments[i].get("startTime") - triple_boundaries[i].get("time")) < 1e-9
            and abs(triple_segments[i].get("endTime") - triple_boundaries[i + 1].get("time")) < 1e-9
            for i in range(len(triple_segments))
        )
    )
    check(
        "三探头中位：按共享交点/采样边界换源、总量 2.875 且片段图表明细同源",
        triple_ok,
        f"{status} {boundary_times} {triple_sources} {body if not triple_ok else ''}",
    )

    # 16. 第三路缺样只拒绝本次三探头分析
    missing_c = {
        "probeA": {"points": passing["points"]},
        "probeB": {"points": passing["points"]},
    }
    status, body = request("POST", f"{API_URL}/api/lethality/triple", missing_c)
    errors = (body or {}).get("detail", {}).get("errors", [])
    check(
        "三探头缺少 probeC 返回 422 且不产出结果",
        status == 422
        and any(e.get("probe") == "probeC" and e.get("field") == "probeC" for e in errors)
        and "medianUnrounded" not in (body or {}),
        f"{status} {body}",
    )

    # 17. 三路共同时间域不一致
    triple_domain = {
        "probeA": {"points": passing["points"]},
        "probeB": {"points": passing["points"]},
        "probeC": {"points": [{"time": t, "temperature": 121.1} for t in (0, 60, 120, 179)]},
    }
    status, body = request("POST", f"{API_URL}/api/lethality/triple", triple_domain)
    errors = (body or {}).get("detail", {}).get("errors", [])
    check(
        "三探头结束时间域不一致返回 422",
        status == 422 and any("共同时间域" in e.get("message", "") for e in errors),
        f"{status} {body}",
    )

    # 18. 旧接口保持兼容：响应不含双/三探头字段
    status, body = request("POST", f"{API_URL}/api/lethality", passing)
    check(
        "单探头接口响应结构保持不变",
        status == 200
        and set(body.keys()) == {"f0", "threshold", "passed", "shortfall", "segments"},
        f"{status} {body}",
    )

    print("=" * 48, flush=True)
    if failures:
        print(f"验收失败：{len(failures)} 项未通过", flush=True)
        for name in failures:
            print(f"  - {name}", flush=True)
        return 1
    print("验收通过：全部检查成功", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
