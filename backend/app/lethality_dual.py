"""双探头保守致死量（下包络）积分。

两支探头的采样时刻不必一致，但都从 0 秒开始、结束于同一秒，且各自满足
单探头的时间/温度/间隔校验（由 validation 负责）。

保守原则：在每个时刻取两支探头中**较低**的致死速率形成下包络，再积分。
不能简单取两份总 F₀ 的较小值——那会高估或低估真实的保守致死量。

插值口径与原梯形法一致：原梯形法在相邻采样点之间隐含一条分段线性的
致死速率线（温度只在采样点换算速率，区间内线性连接），因此这里在两组
采样时刻的并集上，对两条速率线都做分段线性插值。若两条速率线在某个
并集区间内部交换高低，则在交点处拆段，分别积分下包络。
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal

from .lethality import (
    SECONDS_PER_MINUTE,
    THRESHOLD_MINUTES,
    Segment,
    compute_lethality,
    lethality_rate,
    round_half_up,
)

SOURCE_A = "probeA"
SOURCE_B = "probeB"
# 两条速率线在整个区间重合（含端点）：下包络既是 A 也是 B
SOURCE_BOTH = "both"

# 速率比较的相对容差：温度换算速率是 10 的幂，跨度可达 10^4 量级，
# 用相对量判断“相等/交换”，避免浮点尾噪制造虚假交点
RATE_EPS = 1e-12


@dataclass(frozen=True)
class ProbeCurve:
    """一支探头的采样曲线及其独立积分结果。"""

    probe: str
    points: list[tuple[int, float]]
    segments: list[Segment]
    total_unrounded: float
    f0: float  # 四舍五入到两位小数（float，仅展示用）


@dataclass(frozen=True)
class ConservativeSegment:
    """下包络被并集时刻/交点切出的一段。"""

    index: int  # 1-based 段号
    start_time: float
    end_time: float
    duration_seconds: float
    source: str  # probeA / probeB / both：本段下包络取自哪支探头
    start_rate: float  # 下包络在本段起止的致死速率
    end_rate: float
    rate_a_start: float  # 两探头各自在本段起止的速率（图形/明细同源）
    rate_a_end: float
    rate_b_start: float
    rate_b_end: float
    contribution: float  # 未舍入的段贡献（分钟）


@dataclass(frozen=True)
class DualLethalityResult:
    probe_a: ProbeCurve
    probe_b: ProbeCurve
    segments: list[ConservativeSegment]
    conservative_unrounded: float  # 保守总量（未舍入）
    conservative_f0: float  # 四舍五入到两位小数（仅展示）
    threshold: float
    passed: bool  # 用**未舍入**的保守总量与门槛比较
    shortfall: float | None  # 未达标时距门槛的差额（未舍入，分钟）


def _probe_curve(probe: str, points: list[tuple[int, float]]) -> ProbeCurve:
    result = compute_lethality(points)
    return ProbeCurve(
        probe=probe,
        points=points,
        segments=result.segments,
        total_unrounded=result.total_unrounded,
        f0=float(result.f0),
    )


def _sample_rate_at(points: list[tuple[int, float]], t: float) -> float:
    """取探头在时刻 t 的致死速率：采样点用该点速率，区间内线性插值。

    与梯形法隐含的分段线性速率线一致。points 时间严格递增、已校验。
    """
    times = [p[0] for p in points]
    idx = bisect_right(times, t) - 1
    if idx < 0:  # t == 首个时刻之前（理论上不会发生，双探头都从 0 起）
        idx = 0
    t0, temp0 = points[idx]
    rate0 = lethality_rate(temp0)
    if idx + 1 >= len(points) or t == t0:
        return rate0
    t1, temp1 = points[idx + 1]
    rate1 = lethality_rate(temp1)
    if t1 == t0:
        return rate1
    fraction = (t - t0) / (t1 - t0)
    return rate0 + (rate1 - rate0) * fraction


def _rates_close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=RATE_EPS, abs_tol=RATE_EPS)


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _emit_linear_piece(
    pieces: list[dict],
    start: float,
    end: float,
    a_start: float,
    a_end: float,
    b_start: float,
    b_end: float,
    source: str,
    env_start: float,
    env_end: float,
) -> None:
    duration = end - start
    if duration <= 0.0:
        return
    # 梯形法：下包络两端速率取平均后乘时长（分钟）
    contribution = (env_start + env_end) / 2.0 * duration / SECONDS_PER_MINUTE
    pieces.append(
        {
            "start_time": float(start),
            "end_time": float(end),
            "duration_seconds": float(duration),
            "source": source,
            "start_rate": env_start,
            "end_rate": env_end,
            "rate_a_start": a_start,
            "rate_a_end": a_end,
            "rate_b_start": b_start,
            "rate_b_end": b_end,
            "contribution": contribution,
        }
    )


def _classify_side(d_left: float, d_right: float) -> tuple[int, int]:
    """把端点差 (A−B) 归为 -1/0/+1；0 仅在容差内成立。

    不能用裸符号：浮点插值会让本应相等的端点差出 1e-16 的噪声，
    被误判成“区间内部相交”而拆出 ~1e-14 s 的零长度碎段。
    """
    side_left = 0 if _rates_close(d_left, 0.0) else _sign(d_left)
    side_right = 0 if _rates_close(d_right, 0.0) else _sign(d_right)
    return side_left, side_right


def _envelope_pieces(
    points_a: list[tuple[int, float]],
    points_b: list[tuple[int, float]],
) -> list[dict]:
    """在两探头采样时刻的并集（含内部交点）上切出下包络段。"""
    union_times = sorted(
        {float(t) for t, _ in points_a} | {float(t) for t, _ in points_b}
    )

    pieces: list[dict] = []
    for left, right in zip(union_times, union_times[1:]):
        a0 = _sample_rate_at(points_a, left)
        a1 = _sample_rate_at(points_a, right)
        b0 = _sample_rate_at(points_b, left)
        b1 = _sample_rate_at(points_b, right)
        d0 = a0 - b0  # A 相对 B 的高低，正：A 更高，取下包络用 B
        d1 = a1 - b1
        s0, s1 = _classify_side(d0, d1)

        # 两条线性速率线在本并集区间内处处相等 ⇔ 两端差都为 0。
        # 只在一端相等（交点落在并集时刻上）不算重合——两线随后分开。
        if s0 == 0 and s1 == 0:
            _emit_linear_piece(
                pieces, left, right, a0, a1, b0, b1, SOURCE_BOTH,
                (a0 + b0) / 2.0, (a1 + b1) / 2.0,
            )
            continue

        if s0 != 0 and s0 == s1:
            # 整段同一探头更低，无交换
            source = SOURCE_A if s0 < 0 else SOURCE_B
            _emit_linear_piece(
                pieces, left, right, a0, a1, b0, b1, source,
                a0 if source == SOURCE_A else b0,
                a1 if source == SOURCE_A else b1,
            )
            continue

        if s0 == 0 or s1 == 0:
            # 交点恰在本区间的一个端点上（并集时刻）：不拆段、不产生
            # 零长度碎段，整段归属由另一侧谁更低决定；贴线端直接取该线。
            other = s1 if s0 == 0 else s0
            source = SOURCE_A if other < 0 else SOURCE_B
            _emit_linear_piece(
                pieces, left, right, a0, a1, b0, b1, source,
                a0 if source == SOURCE_A else b0,
                a1 if source == SOURCE_A else b1,
            )
            continue

        # 两端严格异号：线性差函数 d(t) 在区间内部有一个零点，必须拆段
        denom = d0 - d1
        fraction = d0 / denom if denom != 0.0 else 0.5
        fraction = min(1.0, max(0.0, fraction))
        t_cross = left + fraction * (right - left)

        ac = a0 + (a1 - a0) * fraction
        bc = b0 + (b1 - b0) * fraction
        # 交点处两线相等；取两者平均抵消插值尾噪
        cross_rate = (ac + bc) / 2.0

        source_left = SOURCE_A if s0 < 0 else SOURCE_B
        source_right = SOURCE_A if s1 < 0 else SOURCE_B
        _emit_linear_piece(
            pieces, left, t_cross, a0, ac, b0, bc, source_left,
            a0 if source_left == SOURCE_A else b0, cross_rate,
        )
        _emit_linear_piece(
            pieces, t_cross, right, ac, a1, bc, b1, source_right,
            cross_rate, a1 if source_right == SOURCE_A else b1,
        )

    return pieces


def compute_dual_lethality(
    points_a: list[tuple[int, float]],
    points_b: list[tuple[int, float]],
) -> DualLethalityResult:
    """计算两支探头的保守（下包络）致死量，并保留各自总量与逐段来源。"""
    if len(points_a) < 2 or len(points_b) < 2:
        raise ValueError("每支探头至少需要两个采样点")
    if points_a[0][0] != 0 or points_b[0][0] != 0:
        raise ValueError("两支探头都必须从 0 秒开始")
    if points_a[-1][0] != points_b[-1][0]:
        raise ValueError("两支探头必须结束于同一秒")

    probe_a = _probe_curve(SOURCE_A, points_a)
    probe_b = _probe_curve(SOURCE_B, points_b)

    raw_pieces = _envelope_pieces(points_a, points_b)
    segments: list[ConservativeSegment] = []
    total = 0.0
    for index, piece in enumerate(raw_pieces, start=1):
        total += piece["contribution"]  # 未舍入累加
        segments.append(ConservativeSegment(index=index, **piece))

    f0_decimal = round_half_up(total)
    threshold = THRESHOLD_MINUTES
    # 放行只用未舍入的保守总量与原门槛比较（不看四舍五入后的展示值）
    passed = Decimal(str(total)) >= threshold
    shortfall = None if passed else float(threshold) - total
    return DualLethalityResult(
        probe_a=probe_a,
        probe_b=probe_b,
        segments=segments,
        conservative_unrounded=total,
        conservative_f0=float(f0_decimal),
        threshold=float(threshold),
        passed=passed,
        shortfall=shortfall,
    )
