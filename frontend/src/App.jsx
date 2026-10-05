import { useState } from 'react';
import { ApiError, calculateLethality } from './api.js';
import { fieldLabel } from './format.js';
import ResultPanel from './ResultPanel.jsx';
import DualProbeView from './DualProbeView.jsx';

// 默认示例：121.1 °C 恒温 180 秒，F₀ 恰为 3.00 min
const DEFAULT_ROWS = [
  { time: '0', temperature: '121.1' },
  { time: '60', temperature: '121.1' },
  { time: '120', temperature: '121.1' },
  { time: '180', temperature: '121.1' },
];

const MIN_ROWS = 2;

function toPayload(rows) {
  // 空值/非数值统一转为 null，交由服务端按行定位报错
  return rows.map((row) => ({
    time: row.time.trim() === '' ? null : Number(row.time),
    temperature: row.temperature.trim() === '' ? null : Number(row.temperature),
  }));
}

export default function App() {
  const [mode, setMode] = useState('single'); // single | dual
  const [rows, setRows] = useState(DEFAULT_ROWS);
  const [result, setResult] = useState(null);
  const [errors, setErrors] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  const errorRows = new Set(
    errors.filter((e) => e.row != null).map((e) => e.row),
  );

  const updateRow = (index, field, value) => {
    setRows((current) =>
      current.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    );
  };

  const addRow = () => {
    setRows((current) => {
      const last = current[current.length - 1];
      const lastTime = last ? Number(last.time) : NaN;
      const canSuggest =
        last && last.time.trim() !== '' && Number.isFinite(lastTime);
      return [
        ...current,
        {
          time: canSuggest ? String(lastTime + 30) : '',
          temperature: last ? last.temperature : '',
        },
      ];
    });
  };

  const removeRow = (index) => {
    setRows((current) => current.filter((_, i) => i !== index));
  };

  const submit = async () => {
    setSubmitting(true);
    try {
      const data = await calculateLethality(toPayload(rows));
      setResult(data);
      setErrors([]);
    } catch (err) {
      // 任一行非法：整次请求失败，清除旧结论
      setResult(null);
      setErrors(
        err instanceof ApiError
          ? err.errors
          : [{ row: null, field: null, message: '请求失败，请稍后重试' }],
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="page">
      <h1>蒸汽杀菌致死量 F₀ 复核</h1>
      <p className="hint">
        录入釜内探头采样：时间从 0 秒起严格递增、相邻间隔 ≤ 60 秒，温度 100.0–140.0
        °C。提交后按梯形法积分，各段未舍入累加，F₀ 四舍五入保留两位小数，达到
        3.00 min 即放行。两支或三支探头采样时刻不一致时，请用多探头复核入口。
      </p>

      <div className="mode-switch" role="tablist" aria-label="复核模式">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'single'}
          className={mode === 'single' ? 'active' : undefined}
          onClick={() => setMode('single')}
        >
          单探头复核
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'dual'}
          className={mode === 'dual' ? 'active' : undefined}
          onClick={() => setMode('dual')}
        >
          双探头保守复核
        </button>
      </div>

      {mode === 'single' ? (
        <>
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
                      aria-label={`时间 第${index + 1}行`}
                      inputMode="numeric"
                      value={row.time}
                      onChange={(e) => updateRow(index, 'time', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`温度 第${index + 1}行`}
                      inputMode="decimal"
                      value={row.temperature}
                      onChange={(e) => updateRow(index, 'temperature', e.target.value)}
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      aria-label={`删除 第${index + 1}行`}
                      onClick={() => removeRow(index)}
                      disabled={rows.length <= MIN_ROWS}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="actions">
            <button type="button" onClick={addRow}>
              添加采样行
            </button>
            <button
              type="button"
              className="primary"
              onClick={submit}
              disabled={submitting}
            >
              {submitting ? '计算中…' : '计算致死量'}
            </button>
          </div>

          {errors.length > 0 && (
            <section className="errors" role="alert" aria-label="校验错误">
              <h2>本次请求被拒绝</h2>
              <ul>
                {errors.map((error, i) => (
                  <li key={i}>
                    {error.row != null
                      ? `第 ${error.row} 行 · ${fieldLabel(error.field)}`
                      : fieldLabel(error.field)}
                    ：{error.message}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <ResultPanel result={result} />
        </>
      ) : (
        <DualProbeView />
      )}
    </main>
  );
}
