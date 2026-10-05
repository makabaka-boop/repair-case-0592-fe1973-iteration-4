import { useState } from 'react';
import { ApiError, calculateDualLethality, calculateTripleLethality } from './api.js';
import { fieldLabel, formatMinutes } from './format.js';
import ProbeChart, { SOURCE_STYLE } from './ProbeChart.jsx';

const MIN_ROWS = 2;

// 默认示例：两支探头采样时刻不一致且速率线多次换源，
// 用于直接演示并集插值与交点拆段；双探头保守总量高于 3.00 min 门槛。
const DEFAULT_PROBE_A = [
  { time: '0', temperature: '126.0' },
  { time: '30', temperature: '123.0' },
  { time: '60', temperature: '121.0' },
  { time: '90', temperature: '124.0' },
  { time: '120', temperature: '127.0' },
];
const DEFAULT_PROBE_B = [
  { time: '0', temperature: '123.0' },
  { time: '45', temperature: '127.0' },
  { time: '90', temperature: '123.0' },
  { time: '120', temperature: '127.0' },
];
// 第三支探头制造局部异常：不直接取三支总 F₀ 的中位值，而是在逐刻速率
// 中位曲线的交点/采样边界拆段后积分。
const DEFAULT_PROBE_C = [
  { time: '0', temperature: '119.0' },
  { time: '40', temperature: '128.0' },
  { time: '80', temperature: '120.0' },
  { time: '120', temperature: '128.0' },
];

const DUAL_PROBES = ['probeA', 'probeB'];
const TRIPLE_PROBES = ['probeA', 'probeB', 'probeC'];

function toPoints(rows) {
  return rows.map((row) => ({
    time: row.time.trim() === '' ? null : Number(row.time),
    temperature: row.temperature.trim() === '' ? null : Number(row.temperature),
  }));
}

function probeName(probe) {
  return SOURCE_STYLE[probe]?.label ?? probe;
}

function ProbeTable({ probe, rows, errorRows, onChange, onAdd, onRemove }) {
  return (
    <div className="probe-editor">
      <h3>{probeName(probe)}</h3>
      <table className="samples">
        <thead>
          <tr>
            <th>行</th>
            <th>时间 (秒)</th>
            <th>温度 (°C)</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={index}
              className={errorRows.has(index + 1) ? 'row-error' : undefined}
            >
              <td className="row-index">{index + 1}</td>
              <td>
                <input
                  aria-label={`${probeName(probe)} 时间 第${index + 1}行`}
                  inputMode="numeric"
                  value={row.time}
                  onChange={(e) => onChange(probe, index, 'time', e.target.value)}
                />
              </td>
              <td>
                <input
                  aria-label={`${probeName(probe)} 温度 第${index + 1}行`}
                  inputMode="decimal"
                  value={row.temperature}
                  onChange={(e) =>
                    onChange(probe, index, 'temperature', e.target.value)
                  }
                />
              </td>
              <td>
                <button
                  type="button"
                  aria-label={`${probeName(probe)} 删除 第${index + 1}行`}
                  onClick={() => onRemove(probe, index)}
                  disabled={rows.length <= MIN_ROWS}
                >
                  删除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" className="add-row" onClick={() => onAdd(probe)}>
        添加采样行
      </button>
    </div>
  );
}

function MultiProbePanel({ result, mode }) {
  const isTriple = mode === 'triple';
  const totalUnrounded = isTriple ? result.medianUnrounded : result.conservativeUnrounded;
  const displayF0 = isTriple ? result.medianF0 : result.conservativeF0;
  const methodLabel = isTriple ? '三探头中位 F₀' : '保守 F₀';
  const probes = isTriple ? TRIPLE_PROBES : DUAL_PROBES;

  return (
    <section
      className={`result dual-result ${result.passed ? 'pass' : 'fail'}`}
      aria-label={isTriple ? '三探头中位复核结果' : '双探头保守复核结果'}
    >
      <h2>{isTriple ? '三探头中位复核结论' : '双探头保守复核结论'}</h2>
      <p className="conclusion" data-testid="dual-conclusion">
        {result.passed
          ? `放行：${methodLabel} = ${formatMinutes(totalUnrounded, 6)} min（展示口径 ${formatMinutes(displayF0)}），达到 ${formatMinutes(result.threshold)} min 门槛`
          : `不放行：${methodLabel} = ${formatMinutes(totalUnrounded, 6)} min（展示口径 ${formatMinutes(displayF0)}），距 ${formatMinutes(result.threshold)} min 门槛尚差 ${formatMinutes(result.shortfall, 6)} min`}
      </p>
      <p className="totals" data-testid="dual-totals">
        {probes.map((probe) => (
          <span key={probe} className="probe-total">
            {probeName(probe)} 总量 {formatMinutes(result[`${probe}TotalUnrounded`], 6)} min（F₀{' '}
            {formatMinutes(result[`${probe}F0`])}）
          </span>
        ))}
        <span>
          {isTriple
            ? '结果取每一时刻三支探头速率的中位值，不是三份总 F₀ 的中位数'
            : '保守总量取每一刻较低速率积分，不是两份总量的较小值'}
        </span>
      </p>

      <ProbeChart result={result} />

      {isTriple && (
        <table className="boundary-table" data-testid="triple-boundaries">
          <thead>
            <tr>
              <th>共享边界</th>
              <th>时间 (s)</th>
              <th>类型</th>
              <th>交点/换序线对</th>
              <th>中位来源</th>
              <th>中位速率</th>
              <th>边界来源说明</th>
            </tr>
          </thead>
          <tbody>
            {result.boundaries.map((boundary) => (
              <tr key={boundary.index} data-boundary-index={boundary.index}>
                <td>{boundary.index}</td>
                <td>{formatMinutes(boundary.time, 6)}</td>
                <td>{boundary.type === 'sample' ? '采样节点' : '曲线交点'}</td>
                <td>
                  {boundary.crossingPairs.length === 0
                    ? '—'
                    : boundary.crossingPairs
                        .map(([a, b]) => `${probeName(a)}/${probeName(b)}`)
                        .join('、')}
                </td>
                <td>
                  <span className={`source-badge source-${boundary.medianSource}`}>
                    {SOURCE_STYLE[boundary.medianSource].label}
                  </span>
                </td>
                <td>{formatMinutes(boundary.medianRate, 6)}</td>
                <td>{boundary.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <table className="segments dual-segments">
        <thead>
          <tr>
            <th>{isTriple ? '中位段' : '保守段'}</th>
            <th>时间区间 (s)</th>
            <th>间隔 (s)</th>
            <th>来源探头</th>
            <th>{isTriple ? '中位速率 起→止' : '下包络速率 起→止'}</th>
            <th>探头A 速率 起→止</th>
            <th>探头B 速率 起→止</th>
            {isTriple && <th>探头C 速率 起→止</th>}
            {isTriple && <th>来源裁决说明</th>}
            <th>段贡献 (min)</th>
          </tr>
        </thead>
        <tbody>
          {result.segments.map((seg) => (
            <tr key={seg.index} data-source={seg.source}>
              <td>{seg.index}</td>
              <td>
                {formatMinutes(seg.startTime, 3)} → {formatMinutes(seg.endTime, 3)}
              </td>
              <td>{formatMinutes(seg.durationSeconds, 3)}</td>
              <td>
                <span className={`source-badge source-${seg.source}`}>
                  {SOURCE_STYLE[seg.source].label}
                </span>
              </td>
              <td>
                {formatMinutes(seg.startRate, 6)} → {formatMinutes(seg.endRate, 6)}
              </td>
              <td>
                {formatMinutes(seg.probeAStartRate, 6)} →{' '}
                {formatMinutes(seg.probeAEndRate, 6)}
              </td>
              <td>
                {formatMinutes(seg.probeBStartRate, 6)} →{' '}
                {formatMinutes(seg.probeBEndRate, 6)}
              </td>
              {isTriple && (
                <td>
                  {formatMinutes(seg.probeCStartRate, 6)} →{' '}
                  {formatMinutes(seg.probeCEndRate, 6)}
                </td>
              )}
              {isTriple && <td className="reason-cell">{seg.sourceReason}</td>}
              <td data-testid={`dual-seg-${seg.index}`}>
                {formatMinutes(seg.contribution, 6)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={isTriple ? 9 : 7}>
              {isTriple ? '中位合计' : '保守合计'}（各段未舍入累加；放行以此值比较门槛）
            </td>
            <td data-testid="dual-total">{formatMinutes(totalUnrounded, 6)}</td>
          </tr>
        </tfoot>
      </table>
    </section>
  );
}

export default function DualProbeView() {
  const [mode, setMode] = useState('dual'); // dual | triple
  const [rowsByProbe, setRowsByProbe] = useState({
    probeA: DEFAULT_PROBE_A,
    probeB: DEFAULT_PROBE_B,
    probeC: DEFAULT_PROBE_C,
  });
  // 双探头维持原失败即清空语义；三探头失败时保留上一份有效三探头报告。
  const [resultByMode, setResultByMode] = useState({ dual: null, triple: null });
  const [errorsByMode, setErrorsByMode] = useState({ dual: [], triple: [] });
  const [submitting, setSubmitting] = useState(false);

  const result = resultByMode[mode];
  const errors = errorsByMode[mode];
  const activeProbes = mode === 'triple' ? TRIPLE_PROBES : DUAL_PROBES;

  const errorRows = (probe) =>
    new Set(
      errors
        .filter((e) => e.probe === probe && e.row != null)
        .map((e) => e.row),
    );

  const updateCell = (probe, index, field, value) => {
    setRowsByProbe((current) => ({
      ...current,
      [probe]: current[probe].map((row, i) =>
        i === index ? { ...row, [field]: value } : row,
      ),
    }));
  };

  const addRow = (probe) => {
    setRowsByProbe((current) => {
      const rows = current[probe];
      const last = rows[rows.length - 1];
      const lastTime = last ? Number(last.time) : NaN;
      const canSuggest = last && last.time.trim() !== '' && Number.isFinite(lastTime);
      return {
        ...current,
        [probe]: [
          ...rows,
          {
            time: canSuggest ? String(lastTime + 30) : '',
            temperature: last ? last.temperature : '',
          },
        ],
      };
    });
  };

  const removeRow = (probe, index) => {
    setRowsByProbe((current) => ({
      ...current,
      [probe]: current[probe].filter((_, i) => i !== index),
    }));
  };

  const submit = async () => {
    setSubmitting(true);
    try {
      const data =
        mode === 'triple'
          ? await calculateTripleLethality(
              toPoints(rowsByProbe.probeA),
              toPoints(rowsByProbe.probeB),
              toPoints(rowsByProbe.probeC),
            )
          : await calculateDualLethality(
              toPoints(rowsByProbe.probeA),
              toPoints(rowsByProbe.probeB),
            );
      setResultByMode((current) => ({ ...current, [mode]: data }));
      setErrorsByMode((current) => ({ ...current, [mode]: [] }));
    } catch (err) {
      const nextErrors =
        err instanceof ApiError
          ? err.errors
          : [{ row: null, field: null, probe: null, message: '请求失败，请稍后重试' }];
      setErrorsByMode((current) => ({ ...current, [mode]: nextErrors }));
      // 双探头旧语义：失败清除本次比较；三探头：只拒绝本次分析，
      // 不覆盖上一份有效三探头报告。
      if (mode === 'dual') {
        setResultByMode((current) => ({ ...current, dual: null }));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const generalErrors = errors.filter((e) => e.row == null);
  const rowErrors = errors.filter((e) => e.row != null);

  return (
    <section className="dual-view">
      <div className="triple-toggle">
        <label>
          <input
            type="checkbox"
            data-testid="triple-mode-toggle"
            checked={mode === 'triple'}
            onChange={(e) => setMode(e.target.checked ? 'triple' : 'dual')}
          />
          启用第三支温度探头（三探头模式）
        </label>
      </div>
      <p className="hint">
        {mode === 'triple'
          ? '三支探头各自从 0 秒开始、结束于同一秒。后端在共同时间域构造三条分段线性致死速率曲线，按采样节点和任两线交点切分；每段按固定 A→B→C 顺序裁决并列中位值后积分，放行只比较未舍入中位总量。'
          : '两支探头各自从 0 秒开始、结束于同一秒，分别遵守时间严格递增、相邻间隔 ≤ 60 秒与温度 100.0–140.0 °C 的校验。后端在两组采样时刻的并集上插值两条致死速率线，在交点拆段后对每一刻较低的速率积分。'}
      </p>

      <div className={`probe-grid probe-count-${activeProbes.length}`}>
        {activeProbes.map((probe) => (
          <ProbeTable
            key={probe}
            probe={probe}
            rows={rowsByProbe[probe]}
            errorRows={errorRows(probe)}
            onChange={updateCell}
            onAdd={addRow}
            onRemove={removeRow}
          />
        ))}
      </div>

      <div className="actions">
        <button
          type="button"
          className="primary"
          onClick={submit}
          disabled={submitting}
          data-testid="dual-submit"
        >
          {submitting
            ? '计算中…'
            : mode === 'triple'
              ? '计算三探头中位 F₀'
              : '计算双探头保守 F₀'}
        </button>
      </div>

      {errors.length > 0 && (
        <section className="errors" role="alert" aria-label="多探头校验错误">
          <h2>
            {mode === 'triple'
              ? '本次三探头分析被拒绝（保留上一份有效三探头报告）'
              : '本次双探头比较被拒绝（已清除本次比较，不影响单探头结论）'}
          </h2>
          <ul>
            {[...generalErrors, ...rowErrors].map((error, i) => {
              const prefix = error.probe ? `${probeName(error.probe)} · ` : '';
              const rowPart = error.row != null ? `第 ${error.row} 行 · ` : '';
              return (
                <li key={i}>
                  {prefix}
                  {rowPart}
                  {fieldLabel(error.field)}：{error.message}
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {result && <MultiProbePanel result={result} mode={mode} />}
    </section>
  );
}
