"""FastAPI 入口：蒸汽杀菌致死量 F₀ 复核。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .lethality import THRESHOLD_MINUTES, compute_lethality, lethality_rate
from .lethality_triple import compute_triple_lethality
from .lethality_dual import compute_dual_lethality
from .validation import (
    ValidationIssue,
    validate_dual_payload,
    validate_payload,
    validate_triple_payload,
)

app = FastAPI(title="蒸汽杀菌致死量 F₀ 复核", version="1.2.0")

# 内部质检工具：放开跨域以便本地开发直连；生产部署经 nginx 同源代理
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _issue_to_dict(issue: ValidationIssue) -> dict:
    # 双探头问题带 probe 标识（probeA/probeB），单探头接口恒为 null
    return {
        "row": issue.row,
        "field": issue.field,
        "message": issue.message,
        "probe": issue.probe,
    }


def _validation_response(issues: list[ValidationIssue]) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "message": "采样数据校验失败，整次请求已拒绝",
                "errors": [_issue_to_dict(issue) for issue in issues],
            }
        },
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/lethality")
async def calculate(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return _validation_response(
            [ValidationIssue(None, "body", "请求体必须为有效的 JSON")]
        )

    points, issues = validate_payload(payload)
    if issues:
        return _validation_response(issues)

    result = compute_lethality(points)
    return {
        "f0": float(result.f0),
        "threshold": float(THRESHOLD_MINUTES),
        "passed": result.passed,
        "shortfall": None if result.shortfall is None else float(result.shortfall),
        "segments": [
            {
                "index": s.index,
                "startTime": s.start_time,
                "endTime": s.end_time,
                "startTemperature": s.start_temperature,
                "endTemperature": s.end_temperature,
                "startRate": s.start_rate,
                "endRate": s.end_rate,
                "durationSeconds": s.duration_seconds,
                # 段贡献保持未舍入：各段之和须能复算未舍入合计，
                # 仅最终 F₀ 四舍五入到两位小数
                "contribution": s.contribution,
            }
            for s in result.segments
        ],
    }


def _probe_curve_dict(curve) -> dict:
    return {
        "probe": curve.probe,
        "points": [
            {"time": t, "temperature": temp, "rate": lethality_rate(temp)}
            for t, temp in curve.points
        ],
        "totalUnrounded": curve.total_unrounded,
        "f0": curve.f0,
    }


@app.post("/api/lethality/triple")
async def calculate_triple(request: Request):
    """三探头中位复核：共享边界、片段表和速率图来自同一计算结果。"""
    try:
        payload = await request.json()
    except Exception:
        return _validation_response(
            [ValidationIssue(None, "body", "请求体必须为有效的 JSON")]
        )

    probes, issues = validate_triple_payload(payload)
    if issues:
        return _validation_response(issues)

    result = compute_triple_lethality(
        probes["probeA"], probes["probeB"], probes["probeC"]
    )

    def boundary_dict(boundary) -> dict:
        return {
            "index": boundary.index,
            "time": boundary.time,
            "type": boundary.type,
            "crossingPairs": [list(pair) for pair in boundary.crossing_pairs],
            "probeARate": boundary.rates[0],
            "probeBRate": boundary.rates[1],
            "probeCRate": boundary.rates[2],
            "medianRate": boundary.median_rate,
            "medianSource": boundary.median_source,
            "reason": boundary.reason,
            "medianReason": boundary.median_reason,
        }

    def segment_dict(segment) -> dict:
        data = {
            "index": segment.index,
            "startBoundaryIndex": segment.index,
            "endBoundaryIndex": segment.index + 1,
            "startTime": segment.start_time,
            "endTime": segment.end_time,
            "durationSeconds": segment.duration_seconds,
            "source": segment.source,
            "sourceReason": segment.source_reason,
            "startRate": segment.start_rate,
            "endRate": segment.end_rate,
            "contribution": segment.contribution,
            "probeAStartRate": segment.probe_rates_start[0],
            "probeAEndRate": segment.probe_rates_end[0],
            "probeBStartRate": segment.probe_rates_start[1],
            "probeBEndRate": segment.probe_rates_end[1],
            "probeCStartRate": segment.probe_rates_start[2],
            "probeCEndRate": segment.probe_rates_end[2],
            "orderedStartRates": [
                {"probe": probe, "rate": rate}
                for probe, rate in segment.ordered_rates_start
            ],
            "orderedEndRates": [
                {"probe": probe, "rate": rate}
                for probe, rate in segment.ordered_rates_end
            ],
        }
        return data

    return {
        "mode": "triple",
        "threshold": result.threshold,
        "probeA": _probe_curve_dict(result.probe_a),
        "probeB": _probe_curve_dict(result.probe_b),
        "probeC": _probe_curve_dict(result.probe_c),
        "probeATotalUnrounded": result.probe_a.total_unrounded,
        "probeBTotalUnrounded": result.probe_b.total_unrounded,
        "probeCTotalUnrounded": result.probe_c.total_unrounded,
        "probeAF0": result.probe_a.f0,
        "probeBF0": result.probe_b.f0,
        "probeCF0": result.probe_c.f0,
        "medianUnrounded": result.median_unrounded,
        "medianF0": result.median_f0,
        "passed": result.passed,
        "shortfall": result.shortfall,
        "boundaries": [boundary_dict(b) for b in result.boundaries],
        "segments": [segment_dict(s) for s in result.segments],
    }


@app.post("/api/lethality/dual")
async def calculate_dual(request: Request):
    """双探头保守复核：两探头各自校验后，在下包络上积分保守 F₀。"""
    try:
        payload = await request.json()
    except Exception:
        return _validation_response(
            [ValidationIssue(None, "body", "请求体必须为有效的 JSON")]
        )

    probes, issues = validate_dual_payload(payload)
    if issues:
        return _validation_response(issues)

    result = compute_dual_lethality(probes["probeA"], probes["probeB"])
    return {
        "threshold": result.threshold,
        "probeA": _probe_curve_dict(result.probe_a),
        "probeB": _probe_curve_dict(result.probe_b),
        "probeATotalUnrounded": result.probe_a.total_unrounded,
        "probeBTotalUnrounded": result.probe_b.total_unrounded,
        "probeAF0": result.probe_a.f0,
        "probeBF0": result.probe_b.f0,
        # 保守总量：未舍入值用于放行判定与逐段复算，f0 仅为展示口径
        "conservativeUnrounded": result.conservative_unrounded,
        "conservativeF0": result.conservative_f0,
        "passed": result.passed,
        "shortfall": result.shortfall,
        "segments": [
            {
                "index": s.index,
                "startTime": s.start_time,
                "endTime": s.end_time,
                "durationSeconds": s.duration_seconds,
                "source": s.source,
                "startRate": s.start_rate,
                "endRate": s.end_rate,
                "probeAStartRate": s.rate_a_start,
                "probeAEndRate": s.rate_a_end,
                "probeBStartRate": s.rate_b_start,
                "probeBEndRate": s.rate_b_end,
                "contribution": s.contribution,
            }
            for s in result.segments
        ],
    }
