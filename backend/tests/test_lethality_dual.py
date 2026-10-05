"""双探头保守致死量测试。

覆盖：
- “解析交点样例”：手工可解的两条分段线性速率线，断言交点位置、
  换源顺序、各段贡献；
- “独立细分积分预言机”：用与实现无关的稠密网格数值积分复算下包络，
  覆盖换源、整段重合、端点换源与未舍入临界判定。
"""

from __future__ import annotations

import math

import pytest

from app.lethality import SECONDS_PER_MINUTE, lethality_rate
from app.lethality_dual import (
    SOURCE_A,
    SOURCE_B,
    SOURCE_BOTH,
    compute_dual_lethality,
)


def temp_for_rate(rate: float) -> float:
    """给定目标致死速率反推温度：rate = 10^((T-121.1)/10)。"""
    return 121.1 + 10.0 * math.log10(rate)


# ---------------------------------------------------------------------------
# 独立预言机：与被测实现完全不同的算法——在 1 ms 稠密网格上逐点取下包络，
# 端点速率取自线性插值，网格内按梯形累加。交点不会落在网格点上时，
# 预言机误差上界 ≈ 每格两侧速率差 × 步长 / 60，约 1e-5 min，故用 1e-3 容差。
# ---------------------------------------------------------------------------


def _linear_rate(points: list[tuple[int, float]], t: float) -> float:
    """与实现无关的速率插值（重新实现一份，不复用被测函数）。"""
    for (t0, temp0), (t1, temp1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            r0, r1 = lethality_rate(temp0), lethality_rate(temp1)
            if t1 == t0:
                return r1
            return r0 + (r1 - r0) * ((t - t0) / (t1 - t0))
    return lethality_rate(points[-1][1])


def oracle_conservative_total(
    points_a: list[tuple[int, float]],
    points_b: list[tuple[int, float]],
    step_seconds: float = 0.01,
) -> float:
    end = points_a[-1][0]
    grid: list[float] = []
    t = 0.0
    while t < end - 1e-12:
        grid.append(min(t, end))
        t += step_seconds
    grid.append(float(end))
    total = 0.0
    for t0, t1 in zip(grid, grid[1:]):
        low0 = min(_linear_rate(points_a, t0), _linear_rate(points_b, t0))
        low1 = min(_linear_rate(points_a, t1), _linear_rate(points_b, t1))
        total += (low0 + low1) / 2.0 * (t1 - t0) / SECONDS_PER_MINUTE
    return total


# ---------------------------------------------------------------------------
# 解析交点样例
# ---------------------------------------------------------------------------


class TestParsedIntersections:
    def test_single_internal_crossing_splits_into_two_named_pieces(self):
        # A: 1 → 3；B: 3 → 1，均在 [0,60] 单段。交点恰在 t=30、rate=2。
        points_a = [(0, temp_for_rate(1.0)), (60, temp_for_rate(3.0))]
        points_b = [(0, temp_for_rate(3.0)), (60, temp_for_rate(1.0))]
        result = compute_dual_lethality(points_a, points_b)

        assert len(result.segments) == 2
        first, second = result.segments
        assert first.source == SOURCE_A  # 交点前 A 更低
        assert second.source == SOURCE_B  # 交点后 B 更低
        assert first.start_time == pytest.approx(0.0)
        assert first.end_time == pytest.approx(30.0)
        assert second.start_time == pytest.approx(30.0)
        assert second.end_time == pytest.approx(60.0)
        # 交点处下包络速率为 2，两端为 1；梯形：(1+2)/2 × 0.5 min = 0.75
        assert first.contribution == pytest.approx(0.75)
        assert second.contribution == pytest.approx(0.75)
        assert first.end_rate == pytest.approx(2.0)
        assert second.start_rate == pytest.approx(2.0)
        assert result.conservative_unrounded == pytest.approx(1.5)
        # 两支探头各自总量相等且都高于保守总量
        assert result.probe_a.total_unrounded == pytest.approx(2.0)
        assert result.probe_b.total_unrounded == pytest.approx(2.0)

    def test_crossing_inside_non_knot_interval_on_union_grid(self):
        # A 的采样时刻 0/30/60，B 的采样时刻 0/20/60；在并集区间 (20,30)
        # 内部相交。手工解：
        #   A 在 (20,30) 恒为插值结果：A(20)=5/3（A 在 0→30 从 1→2），A(30)=2
        #   B 在 (20,60) 从 2→1，B(t)=3 - t/20
        #   令 5/3 + (t-20)/30 = 3 - t/20  →  t = 180/7 ≈ 25.7143
        points_a = [
            (0, temp_for_rate(1.0)),
            (30, temp_for_rate(2.0)),
            (60, temp_for_rate(3.0)),
        ]
        points_b = [
            (0, temp_for_rate(3.0)),
            (20, temp_for_rate(2.0)),
            (60, temp_for_rate(1.0)),
        ]
        result = compute_dual_lethality(points_a, points_b)
        sources = [s.source for s in result.segments]
        # [0,20] A 低；[20,交点] A 低；[交点,30] B 低；[30,60] B 低
        assert sources == [SOURCE_A, SOURCE_A, SOURCE_B, SOURCE_B]
        crossing = result.segments[1]
        assert crossing.end_time == pytest.approx(180.0 / 7.0, abs=1e-9)
        # B 在 (20,60) 由 2 线性降到 1：B(t) = 2.5 - t/40
        rate_at_cross = 2.5 - (180.0 / 7.0) / 40.0
        # 下包络交点速率 = A、B 在该点速率；断言同时给出的 A 侧速率一致
        assert crossing.rate_b_end == pytest.approx(rate_at_cross)
        assert crossing.end_rate == pytest.approx(rate_at_cross)
        assert result.conservative_unrounded == pytest.approx(
            oracle_conservative_total(points_a, points_b), abs=1e-3
        )

    def test_two_crossings_split_in_order(self):
        # A: 恒 2；B: 1→3→1（0→30→60）。B 在 t=15、t=45 两次穿过 A：
        # [0,15] B 低（B 从 1 升到 2），[15,45] A 低（A 恒 2 低于 B 的峰），
        # [45,60] B 低；并集时刻 t=30 再把中间段切成两段。
        points_a = [(0, temp_for_rate(2.0)), (60, temp_for_rate(2.0))]
        points_b = [
            (0, temp_for_rate(1.0)),
            (30, temp_for_rate(3.0)),
            (60, temp_for_rate(1.0)),
        ]
        result = compute_dual_lethality(points_a, points_b)
        sources = [s.source for s in result.segments]
        assert sources == [SOURCE_B, SOURCE_A, SOURCE_A, SOURCE_B]
        boundaries = [
            (s.start_time, s.end_time) for s in result.segments
        ]
        assert boundaries[0] == pytest.approx((0.0, 15.0))
        assert boundaries[1] == pytest.approx((15.0, 30.0))
        assert boundaries[2] == pytest.approx((30.0, 45.0))
        assert boundaries[3] == pytest.approx((45.0, 60.0))
        # 解析保守总量：
        #   [0,15] B 1→2：(1+2)/2×0.25 = 0.375
        #   [15,45] A 恒 2：2×0.5 = 1.0
        #   [45,60] B 2→1：0.375
        assert result.conservative_unrounded == pytest.approx(1.75)

    def test_fully_coincident_lines_marked_both(self):
        # 同一条线（1→3），采样网格不同：B 的中间点必须落在该直线上
        points_a = [(0, temp_for_rate(1.0)), (60, temp_for_rate(3.0))]
        points_b = [
            (0, temp_for_rate(1.0)),
            (30, temp_for_rate(2.0)),
            (60, temp_for_rate(3.0)),
        ]
        result = compute_dual_lethality(points_a, points_b)
        assert {s.source for s in result.segments} == {SOURCE_BOTH}
        assert result.conservative_unrounded == pytest.approx(
            result.probe_a.total_unrounded
        )
        assert result.conservative_unrounded == pytest.approx(
            result.probe_b.total_unrounded
        )

    def test_endpoint_source_switch_emits_no_zero_length_piece(self):
        # 交点恰在并集时刻 t=30（A 的采样点，落在 B 的单段直线上）：
        # A: 1→2→2.5（0→30→60）；B: 3→2（0→60，t=30 时恰为 2.5 之下…）
        # 取 B(t)=3-t/30：t=30 时 B=2，与 A 相等；此前 A 低，此后 B 低。
        points_a = [
            (0, temp_for_rate(1.0)),
            (30, temp_for_rate(2.0)),
            (60, temp_for_rate(2.5)),
        ]
        points_b = [(0, temp_for_rate(3.0)), (60, temp_for_rate(1.0))]
        result = compute_dual_lethality(points_a, points_b)
        assert all(s.duration_seconds > 0 for s in result.segments)
        sources = [s.source for s in result.segments]
        # [0,30] A 低（t=30 两线相等）；[30,60] B 低
        assert sources == [SOURCE_A, SOURCE_B]
        switch = result.segments[0]
        assert switch.end_time == pytest.approx(30.0)
        assert switch.end_rate == pytest.approx(2.0)
        # 解析值：左段 (1+2)/2×0.5 = 0.75；
        # 右段 B 2→1：(2+1)/2×0.5 = 0.75
        assert result.segments[0].contribution == pytest.approx(0.75)
        assert result.segments[1].contribution == pytest.approx(0.75)
        assert result.conservative_unrounded == pytest.approx(1.5)

    def test_touch_at_endpoint_where_one_probe_was_lower(self):
        # 另一端点换源：B 全程低于 A，仅在 t=60 处追平。
        # A: 3→2，B: 1→2。整段（含拆段后）来源都是 B。
        points_a = [(0, temp_for_rate(3.0)), (60, temp_for_rate(2.0))]
        points_b = [(0, temp_for_rate(1.0)), (60, temp_for_rate(2.0))]
        result = compute_dual_lethality(points_a, points_b)
        assert all(s.duration_seconds > 0 for s in result.segments)
        assert all(s.source == SOURCE_B for s in result.segments)
        assert result.conservative_unrounded == pytest.approx(
            result.probe_b.total_unrounded
        )


# ---------------------------------------------------------------------------
# 预言机驱动：换源 / 重合 / 错格 等多组样例
# ---------------------------------------------------------------------------


def make_ramp(times: list[int], rates: list[float]) -> list[tuple[int, float]]:
    return [(t, temp_for_rate(r)) for t, r in zip(times, rates)]


ORACLE_CASES = [
    # 恒 A 低
    (
        make_ramp([0, 60], [1.0, 1.0]),
        make_ramp([0, 60], [2.0, 2.0]),
    ),
    # 内部单次换源
    (
        make_ramp([0, 60], [1.0, 4.0]),
        make_ramp([0, 60], [4.0, 1.0]),
    ),
    # 错格 + 多次换源
    (
        make_ramp([0, 20, 50, 60], [1.0, 3.0, 1.0, 3.0]),
        make_ramp([0, 30, 60], [2.0, 2.0, 2.0]),
    ),
    # 完全重合（不同网格）
    (
        make_ramp([0, 60], [1.0, 3.0]),
        make_ramp([0, 15, 45, 60], [1.0, 1.5, 2.5, 3.0]),
    ),
    # 交点恰好落在共享采样时刻
    (
        make_ramp([0, 30, 60], [1.0, 2.0, 3.0]),
        make_ramp([0, 30, 60], [3.0, 2.0, 3.0]),
    ),
    # 非均匀间隔（间隔上限为 60 s，取到边界）
    (
        make_ramp([0, 60, 90, 150], [5.0, 0.5, 4.0, 1.0]),
        make_ramp([0, 40, 100, 150], [0.5, 5.0, 0.5, 5.0]),
    ),
    # 两次贴线：B 恒 2；A 在 t=20、t=40 两次碰到 2，中间区间两线完全重合
    (
        make_ramp([0, 20, 40, 60], [3.0, 2.0, 2.0, 3.0]),
        make_ramp([0, 60], [2.0, 2.0]),
    ),
]


@pytest.mark.parametrize(("points_a", "points_b"), ORACLE_CASES)
class TestAgainstOracle:
    def test_conservative_total_matches_independent_oracle(self, points_a, points_b):
        result = compute_dual_lethality(points_a, points_b)
        expected = oracle_conservative_total(points_a, points_b)
        assert result.conservative_unrounded == pytest.approx(expected, abs=1e-3)

    def test_segment_contributions_sum_to_total(self, points_a, points_b):
        result = compute_dual_lethality(points_a, points_b)
        assert sum(s.contribution for s in result.segments) == pytest.approx(
            result.conservative_unrounded
        )

    def test_conservative_total_is_no_greater_than_either_probe_total(
        self, points_a, points_b
    ):
        result = compute_dual_lethality(points_a, points_b)
        assert result.conservative_unrounded <= result.probe_a.total_unrounded + 1e-9
        assert result.conservative_unrounded <= result.probe_b.total_unrounded + 1e-9

    def test_reported_probe_rates_match_interpolation(self, points_a, points_b):
        # 每段两端两探头各自的速率必须与独立插值一致，
        # 且下包络速率确实等于两者较小者（重合段两者相等）
        result = compute_dual_lethality(points_a, points_b)
        for seg in result.segments:
            assert seg.rate_a_start == pytest.approx(
                _linear_rate(points_a, seg.start_time)
            )
            assert seg.rate_a_end == pytest.approx(
                _linear_rate(points_a, seg.end_time)
            )
            assert seg.rate_b_start == pytest.approx(
                _linear_rate(points_b, seg.start_time)
            )
            assert seg.rate_b_end == pytest.approx(
                _linear_rate(points_b, seg.end_time)
            )
            assert seg.start_rate == pytest.approx(
                min(seg.rate_a_start, seg.rate_b_start)
            )
            assert seg.end_rate == pytest.approx(
                min(seg.rate_a_end, seg.rate_b_end)
            )

    def test_source_agrees_with_lower_probe(self, points_a, points_b):
        result = compute_dual_lethality(points_a, points_b)
        for seg in result.segments:
            if seg.source == SOURCE_BOTH:
                assert seg.rate_a_start == pytest.approx(seg.rate_b_start)
                assert seg.rate_a_end == pytest.approx(seg.rate_b_end)
            elif seg.source == SOURCE_A:
                assert seg.rate_a_start <= seg.rate_b_start + 1e-9
                assert seg.rate_a_end <= seg.rate_b_end + 1e-9
            else:
                assert seg.source == SOURCE_B
                assert seg.rate_b_start <= seg.rate_a_start + 1e-9
                assert seg.rate_b_end <= seg.rate_a_end + 1e-9

    def test_segments_tile_full_horizon_without_gaps(self, points_a, points_b):
        result = compute_dual_lethality(points_a, points_b)
        assert result.segments[0].start_time == pytest.approx(0.0)
        assert result.segments[-1].end_time == pytest.approx(float(points_a[-1][0]))
        for prev, nxt in zip(result.segments, result.segments[1:]):
            assert nxt.start_time == pytest.approx(prev.end_time)
            assert nxt.index == prev.index + 1


class TestCriticalDecisionUsesUnroundedTotal:
    def _flat_probes(self, rate: float, seconds: int):
        # 两支探头完全相同（保守总量即任一探头总量），恒温恒速
        t = temp_for_rate(rate)
        points = [(0, t), (seconds, t)]
        return points, points

    def test_unrounded_just_below_threshold_fails_even_though_display_rounds_up(self):
        # rate × 180/60 = 2.99996 → 展示四舍五入为 3.00，但未舍入 < 3.00，
        # 保守判定必须不放行
        rate = 2.99996 / 3.0
        points_a, points_b = self._flat_probes(rate, 180)
        result = compute_dual_lethality(points_a, points_b)
        assert result.conservative_unrounded == pytest.approx(2.99996)
        assert result.conservative_f0 == pytest.approx(3.0)
        assert result.passed is False
        assert result.shortfall == pytest.approx(3.0 - 2.99996)

    def test_unrounded_at_or_above_threshold_passes(self):
        rate = 3.00001 / 3.0
        points_a, points_b = self._flat_probes(rate, 180)
        result = compute_dual_lethality(points_a, points_b)
        assert result.conservative_unrounded == pytest.approx(3.00001)
        assert result.passed is True
        assert result.shortfall is None

    def test_exactly_three_minutes_passes(self):
        points = [(0, 121.1), (60, 121.1), (120, 121.1), (180, 121.1)]
        result = compute_dual_lethality(points, points)
        assert result.conservative_unrounded == pytest.approx(3.0)
        assert result.passed is True
        assert result.shortfall is None


class TestInvalidInput:
    def test_mismatched_end_seconds_rejected(self):
        with pytest.raises(ValueError):
            compute_dual_lethality(
                [(0, 121.1), (60, 121.1)],
                [(0, 121.1), (59, 121.1)],
            )

    def test_not_starting_at_zero_rejected(self):
        with pytest.raises(ValueError):
            compute_dual_lethality(
                [(1, 121.1), (60, 121.1)],
                [(0, 121.1), (60, 121.1)],
            )

    def test_too_few_points_rejected(self):
        with pytest.raises(ValueError):
            compute_dual_lethality([(0, 121.1)], [(0, 121.1), (60, 121.1)])
