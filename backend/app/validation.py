"""采样数据校验。

任一行非法都使整次请求失败；每个问题都带 1-based 行号与字段名，
便于前端定位到具体录入行。双探头复核时问题还带探头标识（probeA/probeB），
两支探头各自独立校验，行号在各自探头内从 1 开始。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MIN_POINTS = 2
MAX_INTERVAL_SECONDS = 60
MIN_TEMPERATURE_C = 100.0
MAX_TEMPERATURE_C = 140.0

PROBE_A = "probeA"
PROBE_B = "probeB"
PROBE_C = "probeC"
PROBE_LABELS = {PROBE_A: "探头A", PROBE_B: "探头B", PROBE_C: "探头C"}


@dataclass(frozen=True)
class ValidationIssue:
    row: int | None  # 1-based 行号；None 表示请求整体问题
    field: str  # time / temperature / points / probe / body
    message: str
    probe: str | None = None  # 双探头复核时为 probeA / probeB，单探头接口为 None


def _validate_time(value: Any, row: int, probe: str | None = None) -> ValidationIssue | None:
    if value is None:
        return ValidationIssue(row, "time", "时间为必填项", probe)
    # bool 是 int 的子类，必须显式排除
    if isinstance(value, bool) or not isinstance(value, int):
        return ValidationIssue(row, "time", "时间必须为整数秒", probe)
    if value < 0:
        return ValidationIssue(row, "time", "时间不得为负数", probe)
    return None


def _validate_temperature(value: Any, row: int, probe: str | None = None) -> ValidationIssue | None:
    if value is None:
        return ValidationIssue(row, "temperature", "温度为必填项", probe)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ValidationIssue(row, "temperature", "温度必须为数字", probe)
    temperature = float(value)
    if not math.isfinite(temperature):
        return ValidationIssue(row, "temperature", "温度必须为有限数", probe)
    if not MIN_TEMPERATURE_C <= temperature <= MAX_TEMPERATURE_C:
        return ValidationIssue(
            row,
            "temperature",
            f"温度须在 {MIN_TEMPERATURE_C:.1f} 至 {MAX_TEMPERATURE_C:.1f} °C 之间",
            probe,
        )
    return None


def validate_points(raw_points: Any, probe: str | None = None) -> tuple[
    list[tuple[int, float]], list[ValidationIssue]
]:
    """校验一支探头的采样点数组；问题都标注所属探头（单探头接口为 None）。"""
    issues: list[ValidationIssue] = []
    if not isinstance(raw_points, list):
        return [], [
            ValidationIssue(None, "points", "points 必须为采样点数组", probe)
        ]

    if len(raw_points) < MIN_POINTS:
        issues.append(
            ValidationIssue(None, "points", f"至少需要 {MIN_POINTS} 个采样点", probe)
        )

    times: list[int | None] = []
    temperatures: list[float | None] = []
    for i, raw in enumerate(raw_points):
        row = i + 1
        if not isinstance(raw, dict):
            issues.append(
                ValidationIssue(
                    row, "points", "采样点必须为包含 time 与 temperature 的对象", probe
                )
            )
            times.append(None)
            temperatures.append(None)
            continue
        time_issue = _validate_time(raw.get("time"), row, probe)
        temp_issue = _validate_temperature(raw.get("temperature"), row, probe)
        if time_issue:
            issues.append(time_issue)
        if temp_issue:
            issues.append(temp_issue)
        times.append(raw.get("time") if time_issue is None else None)
        temperatures.append(float(raw.get("temperature")) if temp_issue is None else None)

    # 跨行规则仅在相关时间本身合法时检查，避免级联误报
    if times and times[0] is not None and times[0] != 0:
        issues.append(ValidationIssue(1, "time", "首个采样时间必须为 0 秒", probe))
    for i in range(1, len(times)):
        prev, curr = times[i - 1], times[i]
        if prev is None or curr is None:
            continue
        row = i + 1
        if curr <= prev:
            issues.append(ValidationIssue(row, "time", "时间必须严格递增", probe))
        elif curr - prev > MAX_INTERVAL_SECONDS:
            issues.append(
                ValidationIssue(
                    row,
                    "time",
                    f"相邻采样间隔不得超过 {MAX_INTERVAL_SECONDS} 秒",
                    probe,
                )
            )

    points = [
        (t, temp)
        for t, temp in zip(times, temperatures)
        if t is not None and temp is not None
    ]
    return points, issues


def validate_payload(payload: Any) -> tuple[list[tuple[int, float]], list[ValidationIssue]]:
    """单探头接口：返回 (合法采样点列表, 问题列表)；问题非空时调用方必须拒绝请求。"""
    if not isinstance(payload, dict):
        return [], [ValidationIssue(None, "points", "请求体必须为包含 points 数组的对象")]
    return validate_points(payload.get("points"))


def validate_multi_probe_payload(
    payload: Any,
    probe_names: tuple[str, ...] = (PROBE_A, PROBE_B),
) -> tuple[dict[str, list[tuple[int, float]]], list[ValidationIssue]]:
    """校验多探头请求；每支探头独立遵守单探头的全部采样规则。

    返回以探头名为键的采样点字典。只有所有探头的时间序列本身可用时，
    才检查共同时间域（现有业务要求均从 0 秒开始并结束于同一秒），
    避免在单点、时间非法等错误上叠加跨探头误报。
    """
    if not isinstance(payload, dict):
        if probe_names == (PROBE_A, PROBE_B):
            message = "请求体必须为包含 probeA 与 probeB 两个采样数组的对象"
        else:
            labels = "、".join(PROBE_LABELS[name] for name in probe_names)
            message = f"请求体必须为包含 {labels} 采样数组的对象"
        return {}, [
            ValidationIssue(
                None,
                "body",
                message,
            )
        ]

    issues: list[ValidationIssue] = []
    probes: dict[str, list[tuple[int, float]]] = {}
    valid_series: dict[str, list[tuple[int, float]]] = {}
    for probe in probe_names:
        raw_probe = payload.get(probe)
        if not isinstance(raw_probe, dict):
            issues.append(
                ValidationIssue(
                    None,
                    probe,
                    f"{PROBE_LABELS[probe]}必须为包含 points 数组的对象",
                    probe,
                )
            )
            probes[probe] = []
            continue
        points, probe_issues = validate_points(raw_probe.get("points"), probe)
        probes[probe] = points
        issues.extend(probe_issues)
        time_bad = any(i.field == "time" for i in probe_issues)
        if not time_bad and len(points) >= MIN_POINTS:
            valid_series[probe] = points

    if len(valid_series) == len(probe_names):
        ends = {name: valid_series[name][-1][0] for name in probe_names}
        ends_match = len(set(ends.values())) == 1
        if len(probe_names) == 2:
            end_a = ends[PROBE_A]
            end_b = ends[PROBE_B]
            if end_a != end_b:
                issues.append(
                    ValidationIssue(
                        None,
                        "probe",
                        f"两支探头必须结束于同一秒"
                        f"（{PROBE_LABELS[PROBE_A]}结束于 {end_a} 秒，"
                        f"{PROBE_LABELS[PROBE_B]}结束于 {end_b} 秒）",
                    )
                )
        elif not ends_match:
            details = "，".join(
                f"{PROBE_LABELS[name]} 0–{ends[name]} 秒"
                for name in probe_names
            )
            issues.append(
                ValidationIssue(
                    None,
                    "probe",
                    f"三支探头必须拥有共同时间域（均从 0 秒开始并结束于同一秒；"
                    f"当前 {details}）",
                )
            )

    return probes, issues


def validate_dual_payload(
    payload: Any,
) -> tuple[dict[str, list[tuple[int, float]]], list[ValidationIssue]]:
    """双探头接口：两支探头各自独立遵守单探头的全部校验。"""
    return validate_multi_probe_payload(payload, (PROBE_A, PROBE_B))


def validate_triple_payload(
    payload: Any,
) -> tuple[dict[str, list[tuple[int, float]]], list[ValidationIssue]]:
    """三探头接口：第三路缺样、非法或共同时间域不满足时整次请求拒绝。"""
    return validate_multi_probe_payload(payload, (PROBE_A, PROBE_B, PROBE_C))
