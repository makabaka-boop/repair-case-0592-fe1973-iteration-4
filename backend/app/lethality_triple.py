"""三探头致死量（中位值包络）积分。

三支探头的采样时刻不必一致，但都从 0 秒开始、结束于同一秒。计算时先在
三列采样时刻的并集上构造各自的分段线性致死速率曲线，再把任两条曲线的
内部交点也加入切分边界。每个切开的时间段内，三条线的大小顺序不发生变
化，因此可以确定地取速率中位值对应的一支探头，并在该段上按梯形法积分。

并列中位值按固定探头顺序 A → B → C 裁决：
- 两低值并列：取顺序更靠前的探头；
- 两高值并列：同样取并列的两支中顺序更靠前的探头（它就是中位值）；
- 三条线完全相同：取 probeA。

交点重合、贴线和浮点尾噪也按同一顺序处理。所有真实交点合并为一个共享
边界，绝不输出零时长片段；放行判断只使用未舍入的中位总量。
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
SOURCE_C = "probeC"
SOURCES = (SOURCE_A, SOURCE_B, SOURCE_C)
PROBE_LABELS = {
    SOURCE_A: "探头A",
    SOURCE_B: "探头B",
    SOURCE_C: "探头C",
}

# 与双探头计算一致的相对容差，用于把交点/重合处的浮点尾噪识别为相等。
RATE_EPS = 1e-12
# 同一基础区间内，不同线对算出的交点位置相对区间长度小于该值即视为
# “交点恰好重合”。它只合并数值上已经相同的点，不合并真实近邻交点。
FRACTION_EPS = 1e-10


@dataclass(frozen=True)
class ProbeCurve:
    probe: str
    points: list[tuple[int, float]]
    segments: list[Segment]
    total_unrounded: float
    f0: float


@dataclass(frozen=True)
class MedianSegment:
    index: int
    start_time: float
    end_time: float
    duration_seconds: float
    source: str
    source_reason: str
    start_rate: float
    end_rate: float
    probe_rates_start: tuple[float, float, float]
    probe_rates_end: tuple[float, float, float]
    ordered_rates_start: tuple[tuple[str, float], ...]
    ordered_rates_end: tuple[tuple[str, float], ...]
    contribution: float


@dataclass(frozen=True)
class SharedBoundary:
    index: int
    time: float
    type: str  # sample / crossing
    crossing_pairs: tuple[tuple[str, str], ...]
    rates: tuple[float, float, float]
    median_rate: float
    median_source: str
    reason: str
    median_reason: str


@dataclass(frozen=True)
class TripleLethalityResult:
    probe_a: ProbeCurve
    probe_b: ProbeCurve
    probe_c: ProbeCurve
    boundaries: list[SharedBoundary]
    segments: list[MedianSegment]
    median_unrounded: float
    median_f0: float
    threshold: float
    passed: bool
    shortfall: float | None


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
    """在采样点取该点速率，在采样区间内按速率线性插值。"""
    times = [p[0] for p in points]
    idx = bisect_right(times, t) - 1
    if idx < 0:
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


def _classified_rates(rates: tuple[float, float, float]) -> tuple[
    str, float, tuple[tuple[str, float], ...]
]:
    """按固定 A→B→C 顺序裁决并列中位值。

    返回 (来源探头, 规范化中位速率, 速率从低到高的探头/速率列表)。
    容差内相等的速率会先归入同一组；中位组若包含多支探头，取其中固定
    顺序最靠前的探头，贡献速率使用该组的平均值以抵消交点插值尾噪。
    """
    ordered = sorted(zip(SOURCES, rates), key=lambda item: (item[1], SOURCES.index(item[0])))
    groups: list[list[tuple[str, float]]] = []
    for item in ordered:
        if not groups:
            groups.append([item])
            continue
        anchor = groups[-1][0][1]
        if _rates_close(item[1], anchor):
            groups[-1].append(item)
        else:
            groups.append([item])

    cumulative = 0
    median_group = groups[-1]
    for group in groups:
        cumulative += len(group)
        if cumulative >= 2:
            median_group = group
            break

    # 交点并列时各线理论速率相同；固定顺序只裁决来源探头，积分用并列
    # 组的平均值以抵消不同曲线插值带来的浮点尾噪。
    source = min((item[0] for item in median_group), key=SOURCES.index)
    canonical_rate = sum(item[1] for item in median_group) / len(median_group)
    return source, canonical_rate, tuple(ordered)


def _median_at(
    curves: dict[str, list[tuple[int, float]]], t: float
) -> tuple[str, float, tuple[float, float, float], tuple[tuple[str, float], ...]]:
    rates = tuple(_sample_rate_at(curves[probe], t) for probe in SOURCES)
    source, rate, ordered = _classified_rates(rates)
    return source, rate, rates, ordered


def _signed_difference(value: float) -> int:
    if _rates_close(value, 0.0):
        return 0
    return 1 if value > 0 else -1


def _pair_differences(
    curves: dict[str, list[tuple[int, float]]], t: float
) -> dict[tuple[str, str], float]:
    values = {probe: _sample_rate_at(curves[probe], t) for probe in SOURCES}
    return {
        (SOURCE_A, SOURCE_B): values[SOURCE_A] - values[SOURCE_B],
        (SOURCE_A, SOURCE_C): values[SOURCE_A] - values[SOURCE_C],
        (SOURCE_B, SOURCE_C): values[SOURCE_B] - values[SOURCE_C],
    }


def _interior_crossings(
    curves: dict[str, list[tuple[int, float]]],
    left: float,
    right: float,
) -> list[dict]:
    """找出一个采样并集区间内部的全部成对交点，重合交点合并。"""
    d_left = _pair_differences(curves, left)
    d_right = _pair_differences(curves, right)
    candidates: list[tuple[float, tuple[str, str]]] = []

    for pair, dl in d_left.items():
        dr = d_right[pair]
        sl, sr = _signed_difference(dl), _signed_difference(dr)
        # 端点贴线由相邻段处理；只有严格穿过且零点不在端点上才内部拆段。
        if sl == 0 or sr == 0 or sl == sr:
            continue
        denom = dl - dr
        fraction = dl / denom if denom != 0.0 else 0.5
        if fraction <= FRACTION_EPS or fraction >= 1.0 - FRACTION_EPS:
            continue
        candidates.append((min(1.0, max(0.0, fraction)), pair))

    candidates.sort(key=lambda item: (item[0], item[1]))
    clusters: list[dict] = []
    for fraction, pair in candidates:
        if clusters and abs(fraction - clusters[-1]["fractions"][-1]) <= FRACTION_EPS:
            clusters[-1]["fractions"].append(fraction)
            if pair not in clusters[-1]["pairs"]:
                clusters[-1]["pairs"].append(pair)
        else:
            clusters.append({"fractions": [fraction], "pairs": [pair]})

    crossings = []
    width = right - left
    for cluster in clusters:
        fraction = sum(cluster["fractions"]) / len(cluster["fractions"])
        crossings.append(
            {
                "time": left + fraction * width,
                "kind": "crossing",
                "pairs": tuple(sorted(cluster["pairs"])),
            }
        )
    return crossings


def _node_crossing_pairs(
    curves: dict[str, list[tuple[int, float]]],
    index: int,
    union_times: list[float],
) -> tuple[tuple[str, str], ...]:
    """采样节点上的真实换序：比较相邻两个基础区间中点的大小关系。"""
    pairs: list[tuple[str, str]] = []
    t = union_times[index]
    differences = _pair_differences(curves, t)
    for pair, difference in differences.items():
        if not _rates_close(difference, 0.0):
            continue
        left_sign = right_sign = 0
        if index > 0:
            mid_left = (union_times[index - 1] + t) / 2.0
            left_sign = _signed_difference(_pair_differences(curves, mid_left)[pair])
        if index + 1 < len(union_times):
            mid_right = (t + union_times[index + 1]) / 2.0
            right_sign = _signed_difference(_pair_differences(curves, mid_right)[pair])
        if left_sign != 0 and right_sign != 0 and left_sign != right_sign:
            pairs.append(pair)
    return tuple(sorted(pairs))


def _pair_label(pair: tuple[str, str]) -> str:
    return f"{PROBE_LABELS[pair[0]]}/{PROBE_LABELS[pair[1]]}"


def _boundary_reason(kind: str, pairs: tuple[tuple[str, str], ...]) -> str:
    if kind == "sample":
        if pairs:
            return "采样节点，且 " + "、".join(_pair_label(p) for p in pairs) + " 在此交换高低顺序"
        return "一支或多支探头的采样节点；三条曲线在该点连续取值"
    return "曲线交点：" + "、".join(_pair_label(p) for p in pairs)


def _segment_reason(
    source: str,
    ordered: tuple[tuple[str, float], ...],
    overlapping: bool = False,
) -> str:
    """说明该点/段中位值为何由 source 贡献。ordered 已按速率和固定顺序排列。"""
    source_rate = dict(ordered)[source]
    tied = [probe for probe, rate in ordered if _rates_close(rate, source_rate)]
    tied_sorted = [probe for probe in SOURCES if probe in tied]
    if len(tied_sorted) == 3:
        suffix = "且本整段重合，" if overlapping else ""
        return f"三条曲线并列中位{suffix}按固定 A→B→C 顺序由探头A贡献"
    if len(tied_sorted) == 2:
        remaining = [
            (probe, rate)
            for probe, rate in ordered
            if probe not in tied_sorted
        ]
        tied_are_low = bool(remaining) and remaining[0][1] > source_rate
        position = "低值" if tied_are_low else "高值"
        overlap_text = "且本整段重合" if overlapping else ""
        names = "、".join(PROBE_LABELS[probe] for probe in tied_sorted)
        return (
            f"{names}并列{position}{overlap_text}，按固定 A→B→C 顺序由"
            f"{PROBE_LABELS[source]}贡献中位值"
        )
    rank = [probe for probe, _ in ordered].index(source) + 1
    return f"{PROBE_LABELS[source]}速率在三支探头中唯一排第 {rank}，贡献中位值"


def _build_boundaries_and_segments(
    curves: dict[str, list[tuple[int, float]]],
) -> tuple[list[SharedBoundary], list[MedianSegment]]:
    union_times = sorted(
        {float(t) for probe in SOURCES for t, _ in curves[probe]}
    )
    boundary_rows: list[dict] = []
    for index, t in enumerate(union_times):
        pairs = _node_crossing_pairs(curves, index, union_times)
        boundary_rows.append({"time": float(t), "kind": "sample", "pairs": pairs})

    for left, right in zip(union_times, union_times[1:]):
        boundary_rows.extend(_interior_crossings(curves, left, right))

    boundary_rows.sort(key=lambda row: row["time"])

    # 理论上内部交点不会与采样节点重合；保留去重保护，防止输出零时长段。
    deduped: list[dict] = []
    for row in boundary_rows:
        if deduped and math.isclose(
            row["time"], deduped[-1]["time"], rel_tol=0.0, abs_tol=1e-10
        ):
            # 采样节点的换序信息优先保留，同时合并内部计算可能给出的线对。
            existing_pairs = list(deduped[-1]["pairs"])
            for pair in row["pairs"]:
                if pair not in existing_pairs:
                    existing_pairs.append(pair)
            deduped[-1]["pairs"] = tuple(sorted(existing_pairs))
            deduped[-1]["kind"] = "sample"
        else:
            deduped.append(row)

    boundaries: list[SharedBoundary] = []
    for boundary_index, row in enumerate(deduped, start=1):
        source, median_rate, rates, ordered = _median_at(curves, row["time"])
        pairs = tuple(row["pairs"])
        median_reason = _segment_reason(source, ordered)
        boundaries.append(
            SharedBoundary(
                index=boundary_index,
                time=float(row["time"]),
                type=row["kind"],
                crossing_pairs=pairs,
                rates=rates,
                median_rate=median_rate,
                median_source=source,
                reason=_boundary_reason(row["kind"], pairs),
                median_reason=median_reason,
            )
        )

    segments: list[MedianSegment] = []
    for index, (b_start, b_end) in enumerate(zip(boundaries, boundaries[1:]), start=1):
        start_time = b_start.time
        end_time = b_end.time
        duration = end_time - start_time
        if duration <= 0.0:  # 防御性保护：共享边界构造不应产生零时长片段
            continue

        midpoint = (start_time + end_time) / 2.0
        source, _mid_rate, mid_raw, mid_ordered = _median_at(curves, midpoint)
        _, start_rate, start_raw, start_ordered = _median_at(curves, start_time)
        _, end_rate, end_raw, end_ordered = _median_at(curves, end_time)
        source_index = SOURCES.index(source)
        tied_indices = [
            index
            for index in range(len(SOURCES))
            if _rates_close(mid_raw[index], mid_raw[source_index])
        ]
        overlapping = len(tied_indices) > 1 and all(
            _rates_close(start_raw[index], start_raw[source_index])
            and _rates_close(end_raw[index], end_raw[source_index])
            for index in tied_indices
        )
        contribution = (
            (start_rate + end_rate) / 2.0 * duration / SECONDS_PER_MINUTE
        )
        reason = _segment_reason(source, mid_ordered, overlapping)
        segments.append(
            MedianSegment(
                index=index,
                start_time=float(start_time),
                end_time=float(end_time),
                duration_seconds=float(duration),
                source=source,
                source_reason=reason,
                start_rate=float(start_rate),
                end_rate=float(end_rate),
                probe_rates_start=start_raw,
                probe_rates_end=end_raw,
                ordered_rates_start=start_ordered,
                ordered_rates_end=end_ordered,
                contribution=float(contribution),
            )
        )

    return boundaries, segments


def compute_triple_lethality(
    points_a: list[tuple[int, float]],
    points_b: list[tuple[int, float]],
    points_c: list[tuple[int, float]],
) -> TripleLethalityResult:
    """计算三支探头逐时刻速率中位值的 F₀，并保留共享边界与逐段来源。"""
    curves_data = (
        (SOURCE_A, points_a),
        (SOURCE_B, points_b),
        (SOURCE_C, points_c),
    )
    for _probe, points in curves_data:
        if len(points) < 2:
            raise ValueError("每支探头至少需要两个采样点")
    if any(points[0][0] != 0 for _, points in curves_data):
        raise ValueError("三支探头都必须从 0 秒开始")
    end_times = {points[-1][0] for _, points in curves_data}
    if len(end_times) != 1:
        raise ValueError("三支探头必须结束于同一秒")

    probes = {probe: _probe_curve(probe, points) for probe, points in curves_data}
    curves = {probe: points for probe, points in curves_data}
    boundaries, raw_segments = _build_boundaries_and_segments(curves)

    segments: list[MedianSegment] = []
    total = 0.0
    for segment in raw_segments:
        total += segment.contribution
        segments.append(segment)

    f0_decimal = round_half_up(total)
    passed = Decimal(str(total)) >= THRESHOLD_MINUTES
    shortfall = None if passed else float(THRESHOLD_MINUTES) - total
    return TripleLethalityResult(
        probe_a=probes[SOURCE_A],
        probe_b=probes[SOURCE_B],
        probe_c=probes[SOURCE_C],
        boundaries=boundaries,
        segments=segments,
        median_unrounded=total,
        median_f0=float(f0_decimal),
        threshold=float(THRESHOLD_MINUTES),
        passed=passed,
        shortfall=shortfall,
    )
