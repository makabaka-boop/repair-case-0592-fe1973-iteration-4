/**
 * 多探头速率曲线图：各探头分段线性速率线 + 汇总包络段。
 *
 * 所有几何元素均来自同一份接口响应：
 * - 探头折线使用 probeA/probeB/probeC 的采样点；
 * - 包络粗线与标记使用 segments/boundaries。
 * 因此页面图形、片段表和计算摘要共享同一组边界和来源探头。
 */

const WIDTH = 720;
const HEIGHT = 340;
const MARGIN = { top: 20, right: 24, bottom: 44, left: 56 };

const SOURCE_STYLE = {
  probeA: { color: '#0b6bcb', label: '探头A', dash: '6 3' },
  probeB: { color: '#c05a00', label: '探头B', dash: '2 3' },
  probeC: { color: '#0b7a3b', label: '探头C', dash: '8 2 2 2' },
  both: { color: '#5b3ea6', label: '两探头重合' },
};

function probesFor(result) {
  return ['probeA', 'probeB', 'probeC']
    .filter((probe) => result[probe])
    .map((probe) => ({
      probe,
      points: result[probe].points,
      style: SOURCE_STYLE[probe],
    }));
}

function niceCeil(value) {
  if (value <= 1) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(value)));
  const normalized = value / pow;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * pow;
}

export default function ProbeChart({ result }) {
  const probes = probesFor(result);
  const allPoints = probes.flatMap((probe) => probe.points);
  const maxTime = Math.max(...allPoints.map((p) => p.time));
  const maxRate = niceCeil(Math.max(...allPoints.map((p) => p.rate)));
  const isTriple = Boolean(result.probeC);
  const envelopeLabel = isTriple ? '中位值曲线（按来源着色）' : '保守下包络（按来源着色）';
  const ariaLabel = isTriple
    ? '三探头致死速率曲线与逐刻中位值'
    : '双探头致死速率曲线与保守下包络';

  const plotW = WIDTH - MARGIN.left - MARGIN.right;
  const plotH = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (t) => MARGIN.left + (Number(t) / maxTime) * plotW;
  const y = (r) => MARGIN.top + plotH - (Math.min(r, maxRate) / maxRate) * plotH;

  const linePath = (points) =>
    points
      .map((pt, i) => `${i === 0 ? 'M' : 'L'} ${x(pt.time)} ${y(pt.rate)}`)
      .join(' ');

  const gridRates = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxRate);
  const tickCount = 6;
  const gridTimes = Array.from({ length: tickCount + 1 }, (_, i) =>
    Math.round((maxTime / tickCount) * i),
  );

  return (
    <svg
      className="probe-chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={ariaLabel}
    >
      {gridRates.map((r) => (
        <g key={`r${r}`}>
          <line x1={MARGIN.left} x2={WIDTH - MARGIN.right} y1={y(r)} y2={y(r)} stroke="#e2e8f0" />
          <text x={MARGIN.left - 8} y={y(r) + 4} textAnchor="end" fontSize="11">
            {Number(r.toFixed(3))}
          </text>
        </g>
      ))}
      {gridTimes.map((t) => (
        <g key={`t${t}`}>
          <line y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} x1={x(t)} x2={x(t)} stroke="#f0f3f7" />
          <text x={x(t)} y={HEIGHT - MARGIN.bottom + 18} textAnchor="middle" fontSize="11">
            {t}s
          </text>
        </g>
      ))}

      <line
        x1={MARGIN.left}
        x2={MARGIN.left}
        y1={MARGIN.top}
        y2={HEIGHT - MARGIN.bottom}
        stroke="#94a3b8"
      />
      <line
        x1={MARGIN.left}
        x2={WIDTH - MARGIN.right}
        y1={HEIGHT - MARGIN.bottom}
        y2={HEIGHT - MARGIN.bottom}
        stroke="#94a3b8"
      />
      <text x={MARGIN.left - 40} y={MARGIN.top - 6} fontSize="11">
        致死速率
      </text>

      {probes.map(({ probe, points, style }) => (
        <path
          key={probe}
          d={linePath(points)}
          fill="none"
          stroke={style.color}
          strokeWidth="1.6"
          strokeDasharray={style.dash}
        />
      ))}

      {result.segments.map((seg) => (
        <line
          key={`env${seg.index}`}
          data-testid={`envelope-segment-${seg.index}`}
          data-segment-index={seg.index}
          data-start-boundary-index={seg.startBoundaryIndex ?? seg.index}
          data-end-boundary-index={seg.endBoundaryIndex ?? seg.index + 1}
          x1={x(seg.startTime)}
          y1={y(seg.startRate)}
          x2={x(seg.endTime)}
          y2={y(seg.endRate)}
          stroke={SOURCE_STYLE[seg.source].color}
          strokeWidth="4"
          strokeLinecap="butt"
        >
          <title>
            {`第${seg.index}段 · ${SOURCE_STYLE[seg.source].label} · ${seg.contribution.toFixed(6)} min${
              seg.sourceReason ? `\n${seg.sourceReason}` : ''
            }`}
          </title>
        </line>
      ))}

      {/* 内部共享边界：双探头为交点；三探头还可能是采样节点上的换序。 */}
      {(result.boundaries
        ? result.boundaries.slice(1, -1)
        : result.segments.slice(1)
      ).map((boundary) => {
        const time = boundary.time ?? boundary.startTime;
        const rate = boundary.medianRate ?? boundary.startRate;
        const reason = boundary.reason ?? '曲线交点';
        const isCrossing = !boundary.type || boundary.type === 'crossing';
        return (
          <circle
            key={`boundary-${boundary.index}`}
            data-testid={`shared-boundary-${boundary.index}`}
            data-boundary-index={boundary.index}
            cx={x(time)}
            cy={y(rate)}
            r={isCrossing ? 3.8 : 3.2}
            fill={isCrossing ? '#fff' : '#1f2933'}
            stroke="#1f2933"
            strokeWidth="1.5"
          >
            <title>{`${Number(time).toFixed(6)}s · ${reason}`}</title>
          </circle>
        );
      })}

      <g transform={`translate(${MARGIN.left + 8}, ${MARGIN.top + 4})`}>
        <rect width="168" height={20 + probes.length * 18 + 20} rx="4" fill="#ffffffcc" stroke="#d9e2ec" />
        {probes.map(({ probe, style }, index) => (
          <g key={`legend-${probe}`} transform={`translate(0, ${index * 18})`}>
            <line
              x1="8"
              y1="14"
              x2="34"
              y2="14"
              stroke={style.color}
              strokeWidth="1.6"
              strokeDasharray={style.dash}
            />
            <text x="40" y="18" fontSize="11">
              {style.label} 速率线
            </text>
          </g>
        ))}
        <line
          x1="8"
          y1={20 + probes.length * 18}
          x2="34"
          y2={20 + probes.length * 18}
          stroke="#1f2933"
          strokeWidth="4"
        />
        <text x="40" y={4 + 20 + probes.length * 18} fontSize="11">
          {envelopeLabel}
        </text>
      </g>
    </svg>
  );
}

export { SOURCE_STYLE };
