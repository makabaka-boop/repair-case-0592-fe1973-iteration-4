"""F₀（致死量）积分计算。

业务约定：
- 每个采样点的致死速率为 10 ** ((T - 121.1) / 10)；
- 相邻两点按梯形法求面积，乘以秒差后再除以 60 换算为分钟；
- 各段贡献以未舍入的值累加，最终 F₀ 按四舍五入保留两位小数；
- F₀ 达到 3.00 分钟即判定放行。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

REFERENCE_TEMPERATURE_C = 121.1
Z_VALUE_C = 10.0
SECONDS_PER_MINUTE = 60.0
THRESHOLD_MINUTES = Decimal("3.00")
CENT = Decimal("0.01")


def lethality_rate(temperature_c: float) -> float:
    """单一采样点的致死速率（相对 121.1 °C 的等效倍率）。"""
    return 10.0 ** ((temperature_c - REFERENCE_TEMPERATURE_C) / Z_VALUE_C)


def round_half_up(value: float, quantum: Decimal = CENT) -> Decimal:
    """按“四舍五入”保留指定位数（区别于 Python 默认的银行家舍入）。"""
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Segment:
    """相邻两个采样点构成的一段积分。"""

    index: int  # 1-based 段号
    start_time: int
    end_time: int
    start_temperature: float
    end_temperature: float
    start_rate: float
    end_rate: float
    duration_seconds: int
    contribution: float  # 未舍入的段贡献（分钟）


@dataclass(frozen=True)
class LethalityResult:
    segments: list[Segment]
    total_unrounded: float
    f0: Decimal  # 四舍五入到两位小数
    passed: bool
    shortfall: Decimal | None  # 未达标时距门槛的差额；达标为 None


def compute_lethality(points: list[tuple[int, float]]) -> LethalityResult:
    """对 (time_seconds, temperature_c) 序列做梯形积分。"""
    if len(points) < 2:
        raise ValueError("至少需要两个采样点")

    segments: list[Segment] = []
    total = 0.0
    for index, ((t0, temp0), (t1, temp1)) in enumerate(
        zip(points, points[1:]), start=1
    ):
        rate0 = lethality_rate(temp0)
        rate1 = lethality_rate(temp1)
        duration = t1 - t0
        # 梯形法：两端点致死速率取平均后乘以时长（分钟）
        contribution = (rate0 + rate1) / 2.0 * duration / SECONDS_PER_MINUTE
        total += contribution  # 未舍入累加
        segments.append(
            Segment(
                index=index,
                start_time=t0,
                end_time=t1,
                start_temperature=temp0,
                end_temperature=temp1,
                start_rate=rate0,
                end_rate=rate1,
                duration_seconds=duration,
                contribution=contribution,
            )
        )

    f0 = round_half_up(total)
    # 放行判定以四舍五入后的最终 F₀ 为准，与页面展示同一口径，
    # 避免出现“展示 3.00 却不放行、尚差 0.00”的矛盾结论
    passed = f0 >= THRESHOLD_MINUTES
    shortfall = None if passed else THRESHOLD_MINUTES - f0
    return LethalityResult(
        segments=segments,
        total_unrounded=total,
        f0=f0,
        passed=passed,
        shortfall=shortfall,
    )
