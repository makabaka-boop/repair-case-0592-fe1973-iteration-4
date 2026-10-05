import { formatMinutes } from './format.js';

export default function ResultPanel({ result }) {
  if (!result) return null;

  const f0 = formatMinutes(result.f0);
  const threshold = formatMinutes(result.threshold);

  return (
    <section
      className={`result ${result.passed ? 'pass' : 'fail'}`}
      aria-label="计算结果"
    >
      <h2>复核结论</h2>
      <p className="conclusion" data-testid="conclusion">
        {result.passed
          ? `放行：F₀ = ${f0} min，达到 ${threshold} min 门槛`
          : `不放行：F₀ = ${f0} min，距 ${threshold} min 门槛尚差 ${formatMinutes(result.shortfall)} min`}
      </p>

      <table className="segments">
        <thead>
          <tr>
            <th>段</th>
            <th>时间区间 (s)</th>
            <th>温度区间 (°C)</th>
            <th>间隔 (s)</th>
            <th>致死速率 起→止</th>
            <th>段贡献 (min)</th>
          </tr>
        </thead>
        <tbody>
          {result.segments.map((s) => (
            <tr key={s.index}>
              <td>{s.index}</td>
              <td>
                {s.startTime} → {s.endTime}
              </td>
              <td>
                {s.startTemperature} → {s.endTemperature}
              </td>
              <td>{s.durationSeconds}</td>
              <td>
                {formatMinutes(s.startRate, 6)} → {formatMinutes(s.endRate, 6)}
              </td>
              <td>{formatMinutes(s.contribution, 6)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={5}>合计 F₀（各段未舍入累加后四舍五入）</td>
            <td data-testid="f0-total">{f0}</td>
          </tr>
        </tfoot>
      </table>
    </section>
  );
}
