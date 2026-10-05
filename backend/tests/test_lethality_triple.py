"""三探头中位致死量测试。

覆盖手算交点、并列中位值的固定顺序裁决、交点重合、共享边界连续性，
以及独立稠密网格预言机对换源和积分的复算。
"""

from __future__ import annotations

import math

import pytest

from app.lethality import SECONDS_PER_MINUTE, lethality_rate
from app.lethality_triple import (
    SOURCE_A,
    SOURCE_B,
    SOURCE_C,
    compute_triple_lethality,
)


def temp_for_rate(rate: float) -> float:
    return 121.1 + 10.0 * math.log10(rate)


def ramp(times: list[int], rates: list[float]) -> list[tuple[int, float]]:
    return [(t, temp_for_rate(r)) for t, r in zip(times, rates)]


def independent_linear_rate(points: list[tuple[int, float]], t: float) -> float:
    """测试内独立实现的线性速率插值，不复用生产代码。"""
    for (t0, temp0), (t1, temp1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            r0 = lethality_rate(temp0)
            r1 = lethality_rate(temp1)
            return r0 + (r1 - r0) * ((t - t0) / (t1 - t0))
    return lethality_rate(points[-1][1])


def oracle_median_total(curves: list[list[tuple[int, float]]], step: float = 0.01) -> float:
    end = curves[0][-1][0]
    times = []
    t = 0.0
    while t < end - 1e-12:
        times.append(min(t, end))
        t += step
    times.append(float(end))

    total = 0.0
    for left, right in zip(times, times[1:]):
        left_rates = sorted(independent_linear_rate(curve, left) for curve in curves)
        right_rates = sorted(independent_linear_rate(curve, right) for curve in curves)
        total += (left_rates[1] + right_rates[1]) / 2.0 * (right - left) / SECONDS_PER_MINUTE
    return total


class TestParsedTripleIntersections:
    def test_ties_and_knots_switch_median_source_with_known_integral(self):
        # A: 1→5；B: 5→1；C: 2→4→2。
        # t=22.5 B/C 高值相交，中位由 C 切到 B；
        # t=30 采样节点 A/B 低值相交，中位由 B 切到 A；
        # t=37.5 A/C 相交，此后中位再切回 C。
        points_a = ramp([0, 60], [1.0, 5.0])
        points_b = ramp([0, 60], [5.0, 1.0])
        points_c = ramp([0, 30, 60], [2.0, 4.0, 2.0])
        result = compute_triple_lethality(points_a, points_b, points_c)
        boundaries = result.boundaries

        assert len(boundaries) == 5
        assert [b.time for b in boundaries] == pytest.approx(
            [0.0, 22.5, 30.0, 37.5, 60.0]
        )
        assert [b.type for b in boundaries] == [
            "sample",
            "crossing",
            "sample",
            "crossing",
            "sample",
        ]
        assert boundaries[1].crossing_pairs == ((SOURCE_B, SOURCE_C),)
        assert boundaries[2].crossing_pairs == ((SOURCE_A, SOURCE_B),)
        assert boundaries[3].crossing_pairs == ((SOURCE_A, SOURCE_C),)

        assert [s.source for s in result.segments] == [
            SOURCE_C,
            SOURCE_B,
            SOURCE_A,
            SOURCE_C,
        ]
        contributions = [s.contribution for s in result.segments]
        assert contributions == pytest.approx(
            [1.03125, 0.40625, 0.40625, 1.03125]
        )
        assert result.median_unrounded == pytest.approx(2.875)
        assert sum(contributions) == pytest.approx(result.median_unrounded)
        assert result.segments[1].source == SOURCE_B
        assert "唯一排第 2" in result.segments[1].source_reason
        # t=30 左端点 A/B 低值并列，按固定顺序在边界上裁给 A；
        # 进入右侧开区间后 A 是唯一中位。
        assert "并列低值" in result.boundaries[2].median_reason
        assert "唯一排第 2" in result.segments[2].source_reason

    def test_three_curves_meet_at_same_interior_crossing_create_one_boundary(self):
        points_a = ramp([0, 60], [1.0, 5.0])
        points_b = ramp([0, 60], [5.0, 1.0])
        points_c = ramp([0, 60], [3.0, 3.0])
        result = compute_triple_lethality(points_a, points_b, points_c)

        assert len(result.boundaries) == 3
        crossing = result.boundaries[1]
        assert crossing.time == pytest.approx(30.0)
        assert set(crossing.crossing_pairs) == {
            (SOURCE_A, SOURCE_B),
            (SOURCE_A, SOURCE_C),
            (SOURCE_B, SOURCE_C),
        }
        # 三线重合点的并列中位固定由 A 裁决。
        assert crossing.median_source == SOURCE_A
        assert crossing.median_rate == pytest.approx(3.0)
        assert len(result.segments) == 2
        assert all(s.duration_seconds > 0 for s in result.segments)
        assert all(s.source == SOURCE_C for s in result.segments)
        assert result.median_unrounded == pytest.approx(3.0)

    def test_three_curves_meet_at_same_sample_node_create_one_boundary(self):
        # A 从低到高再到低；B=C 恒 3。t=30 时三线在采样节点相遇，但线对
        # 并未跨节点交换高低；采样节点仍作为共享边界，B/C 重合线固定取 B。
        points_a = ramp([0, 30, 60], [1.0, 3.0, 1.0])
        points_b = ramp([0, 60], [3.0, 3.0])
        points_c = ramp([0, 30, 60], [3.0, 3.0, 3.0])
        result = compute_triple_lethality(points_a, points_b, points_c)
        node = result.boundaries[1]

        assert node.time == pytest.approx(30.0)
        assert node.type == "sample"
        assert node.crossing_pairs == ()
        # 节点瞬时三线并列，按固定顺序把该点裁给 A；两侧开区间仍取 B。
        assert node.median_source == SOURCE_A
        assert len(result.segments) == 2
        assert [s.source for s in result.segments] == [SOURCE_B, SOURCE_B]

    def test_all_three_coincident_uses_fixed_probe_a_arbitration(self):
        points_a = ramp([0, 60], [1.0, 4.0])
        points_b = ramp([0, 20, 40, 60], [1.0, 2.0, 3.0, 4.0])
        points_c = ramp([0, 30, 60], [1.0, 2.5, 4.0])
        result = compute_triple_lethality(points_a, points_b, points_c)

        assert all(s.source == SOURCE_A for s in result.segments)
        assert all("三条曲线并列中位" in s.source_reason for s in result.segments)
        assert result.median_unrounded == pytest.approx(
            result.probe_a.total_unrounded
        )
        assert result.median_unrounded == pytest.approx(
            result.probe_b.total_unrounded
        )
        assert result.median_unrounded == pytest.approx(
            result.probe_c.total_unrounded
        )

    def test_two_probes_coincident_as_median_through_an_interval(self):
        # A=B 恒为 2，C 从 4 降到 0.5；整段中位是 A/B 重合线，固定取 A。
        points_a = ramp([0, 60], [2.0, 2.0])
        points_b = ramp([0, 30, 60], [2.0, 2.0, 2.0])
        points_c = ramp([0, 60], [4.0, 0.5])
        result = compute_triple_lethality(points_a, points_b, points_c)

        assert all(s.source == SOURCE_A for s in result.segments)
        assert all("本整段重合" in s.source_reason for s in result.segments)
        assert result.median_unrounded == pytest.approx(2.0)

    def test_fixed_order_for_two_low_and_two_high_ties(self):
        # 0 秒：A=B=1 为两低值，C=3；中位固定 A。
        low_a = ramp([0, 60], [1.0, 1.0])
        low_b = ramp([0, 60], [1.0, 2.0])
        high_c = ramp([0, 60], [3.0, 3.0])
        result = compute_triple_lethality(low_a, low_b, high_c)
        assert result.boundaries[0].median_source == SOURCE_A
        assert "并列低值" in result.boundaries[0].median_reason
        # 离开 0 秒后 B 立即高于 A，段内 A 最低、C=3 最高，唯一中位为 B。
        assert result.segments[0].source == SOURCE_B

        # 0 秒：C=1 低，A=B=3 为两高值；中位固定 A 而不是 B。
        high_a = ramp([0, 60], [3.0, 3.0])
        high_b = ramp([0, 60], [3.0, 2.0])
        low_c = ramp([0, 60], [1.0, 1.0])
        result = compute_triple_lethality(high_a, high_b, low_c)
        assert result.boundaries[0].median_source == SOURCE_A
        assert "并列高值" in result.boundaries[0].median_reason
        # 离开 0 秒后 B 立即低于 A，段内唯一中位为 B。
        assert result.segments[0].source == SOURCE_B


ORACLE_CASES = [
    # 恒定三线
    (
        ramp([0, 60, 120], [1.0, 2.0, 1.0]),
        ramp([0, 30, 120], [2.0, 1.0, 2.0]),
        ramp([0, 45, 90, 120], [3.0, 0.5, 3.0, 0.5]),
    ),
    # 手算换源样例
    (
        ramp([0, 60], [1.0, 5.0]),
        ramp([0, 60], [5.0, 1.0]),
        ramp([0, 30, 60], [2.0, 4.0, 2.0]),
    ),
    # 错格、多次穿过中位
    (
        ramp([0, 20, 50, 90], [0.5, 5.0, 0.5, 4.0]),
        ramp([0, 30, 70, 90], [4.0, 0.5, 5.0, 0.5]),
        ramp([0, 15, 45, 90], [2.0, 3.0, 1.0, 3.0]),
    ),
    # 两条线长期重合且共同位于中位
    (
        ramp([0, 20, 40, 60], [2.0, 2.0, 2.0, 2.0]),
        ramp([0, 60], [2.0, 2.0]),
        ramp([0, 60], [4.0, 0.5]),
    ),
]


@pytest.mark.parametrize(("points_a", "points_b", "points_c"), ORACLE_CASES)
class TestTripleAgainstOracle:
    def test_total_matches_independent_oracle(self, points_a, points_b, points_c):
        result = compute_triple_lethality(points_a, points_b, points_c)
        expected = oracle_median_total([points_a, points_b, points_c])
        assert result.median_unrounded == pytest.approx(expected, abs=1e-3)

    def test_segments_share_boundaries_and_tile_horizon(
        self, points_a, points_b, points_c
    ):
        result = compute_triple_lethality(points_a, points_b, points_c)
        assert result.boundaries[0].time == pytest.approx(0.0)
        assert result.boundaries[-1].time == pytest.approx(float(points_a[-1][0]))
        for index, segment in enumerate(result.segments, start=1):
            assert segment.index == index
            assert segment.duration_seconds > 0
            assert segment.start_time == pytest.approx(result.boundaries[index - 1].time)
            assert segment.end_time == pytest.approx(result.boundaries[index].time)
        assert len(result.segments) == len(result.boundaries) - 1

    def test_boundary_and_segment_rates_are_same_shared_values(
        self, points_a, points_b, points_c
    ):
        result = compute_triple_lethality(points_a, points_b, points_c)
        for segment in result.segments:
            left = result.boundaries[segment.index - 1]
            right = result.boundaries[segment.index]
            assert segment.start_rate == pytest.approx(left.median_rate)
            assert segment.end_rate == pytest.approx(right.median_rate)
            assert segment.probe_rates_start == pytest.approx(left.rates)
            assert segment.probe_rates_end == pytest.approx(right.rates)

    def test_reported_source_is_midpoint_median(
        self, points_a, points_b, points_c
    ):
        curves = [points_a, points_b, points_c]
        result = compute_triple_lethality(points_a, points_b, points_c)
        for segment in result.segments:
            midpoint = (segment.start_time + segment.end_time) / 2.0
            rates = [independent_linear_rate(curve, midpoint) for curve in curves]
            sorted_rates = sorted(rates)
            source_index = (SOURCE_A, SOURCE_B, SOURCE_C).index(segment.source)
            assert rates[source_index] == pytest.approx(sorted_rates[1], abs=1e-9)

    def test_contributions_sum_to_unrounded_total(
        self, points_a, points_b, points_c
    ):
        result = compute_triple_lethality(points_a, points_b, points_c)
        assert sum(s.contribution for s in result.segments) == pytest.approx(
            result.median_unrounded
        )


class TestTripleThreshold:
    def test_unrounded_just_below_threshold_fails_even_display_rounds_to_three(self):
        rate = 2.99996 / 3.0
        points = [(0, temp_for_rate(rate)), (180, temp_for_rate(rate))]
        result = compute_triple_lethality(points, points, points)
        assert result.median_unrounded == pytest.approx(2.99996)
        assert result.median_f0 == pytest.approx(3.0)
        assert result.passed is False
        assert result.shortfall == pytest.approx(0.00004)

    def test_exactly_threshold_passes(self):
        points = [(0, 121.1), (60, 121.1), (120, 121.1), (180, 121.1)]
        result = compute_triple_lethality(points, points, points)
        assert result.median_unrounded == pytest.approx(3.0)
        assert result.passed is True
        assert result.shortfall is None


class TestTripleInvalidInput:
    def test_mismatched_end_seconds_rejected(self):
        with pytest.raises(ValueError):
            compute_triple_lethality(
                [(0, 121.1), (60, 121.1)],
                [(0, 121.1), (60, 121.1)],
                [(0, 121.1), (59, 121.1)],
            )

    def test_too_few_points_rejected(self):
        with pytest.raises(ValueError):
            compute_triple_lethality(
                [(0, 121.1)],
                [(0, 121.1), (60, 121.1)],
                [(0, 121.1), (60, 121.1)],
            )
