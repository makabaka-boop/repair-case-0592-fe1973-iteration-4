import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App.jsx';

// 含内部交点拆段的双探头响应：来源序列 probeA → probeB
const dualCrossingResponse = {
  threshold: 3.0,
  probeA: {
    probe: 'probeA',
    points: [
      { time: 0, temperature: 100, rate: 1 },
      { time: 30, temperature: 110, rate: 2 },
      { time: 60, temperature: 115, rate: 3 },
    ],
    totalUnrounded: 2.0,
    f0: 2.0,
  },
  probeB: {
    probe: 'probeB',
    points: [
      { time: 0, temperature: 115, rate: 3 },
      { time: 60, temperature: 100, rate: 1 },
    ],
    totalUnrounded: 2.0,
    f0: 2.0,
  },
  probeATotalUnrounded: 2.0,
  probeBTotalUnrounded: 2.0,
  probeAF0: 2.0,
  probeBF0: 2.0,
  conservativeUnrounded: 1.5,
  conservativeF0: 1.5,
  passed: false,
  shortfall: 1.5,
  segments: [
    {
      index: 1,
      startTime: 0,
      endTime: 30,
      durationSeconds: 30,
      source: 'probeA',
      startRate: 1,
      endRate: 2,
      probeAStartRate: 1,
      probeAEndRate: 2,
      probeBStartRate: 3,
      probeBEndRate: 2,
      contribution: 0.75,
    },
    {
      index: 2,
      startTime: 30,
      endTime: 60,
      durationSeconds: 30,
      source: 'probeB',
      startRate: 2,
      endRate: 1,
      probeAStartRate: 2,
      probeAEndRate: 3,
      probeBStartRate: 2,
      probeBEndRate: 1,
      contribution: 0.75,
    },
  ],
};

const tripleResponse = {
  mode: 'triple',
  threshold: 3.0,
  probeA: {
    probe: 'probeA',
    points: [
      { time: 0, temperature: 100, rate: 1 },
      { time: 60, temperature: 115, rate: 5 },
    ],
    totalUnrounded: 3,
    f0: 3,
  },
  probeB: {
    probe: 'probeB',
    points: [
      { time: 0, temperature: 115, rate: 5 },
      { time: 60, temperature: 100, rate: 1 },
    ],
    totalUnrounded: 3,
    f0: 3,
  },
  probeC: {
    probe: 'probeC',
    points: [
      { time: 0, temperature: 105, rate: 2 },
      { time: 30, temperature: 112, rate: 4 },
      { time: 60, temperature: 105, rate: 2 },
    ],
    totalUnrounded: 2.8,
    f0: 2.8,
  },
  probeATotalUnrounded: 3,
  probeBTotalUnrounded: 3,
  probeCTotalUnrounded: 2.8,
  probeAF0: 3,
  probeBF0: 3,
  probeCF0: 2.8,
  medianUnrounded: 2.875,
  medianF0: 2.88,
  passed: false,
  shortfall: 0.125,
  boundaries: [
    { index: 1, time: 0, type: 'sample', crossingPairs: [], probeARate: 1, probeBRate: 5, probeCRate: 2, medianRate: 2, medianSource: 'probeC', reason: '采样节点' },
    { index: 2, time: 22.5, type: 'crossing', crossingPairs: [['probeB', 'probeC']], probeARate: 2.5, probeBRate: 3.5, probeCRate: 3.5, medianRate: 3.5, medianSource: 'probeB', reason: '曲线交点：探头B/探头C' },
    { index: 3, time: 30, type: 'sample', crossingPairs: [['probeA', 'probeB']], probeARate: 3, probeBRate: 3, probeCRate: 4, medianRate: 3, medianSource: 'probeA', reason: '采样节点换序' },
    { index: 4, time: 37.5, type: 'crossing', crossingPairs: [['probeA', 'probeC']], probeARate: 3.5, probeBRate: 2.5, probeCRate: 3.5, medianRate: 3.5, medianSource: 'probeC', reason: '曲线交点：探头A/探头C' },
    { index: 5, time: 60, type: 'sample', crossingPairs: [], probeARate: 5, probeBRate: 1, probeCRate: 2, medianRate: 2, medianSource: 'probeC', reason: '采样节点' },
  ],
  segments: [
    { index: 1, startBoundaryIndex: 1, endBoundaryIndex: 2, startTime: 0, endTime: 22.5, durationSeconds: 22.5, source: 'probeC', sourceReason: '探头C唯一排第 2', startRate: 2, endRate: 3.5, probeAStartRate: 1, probeAEndRate: 2.5, probeBStartRate: 5, probeBEndRate: 3.5, probeCStartRate: 2, probeCEndRate: 3.5, contribution: 1.03125 },
    { index: 2, startBoundaryIndex: 2, endBoundaryIndex: 3, startTime: 22.5, endTime: 30, durationSeconds: 7.5, source: 'probeB', sourceReason: '探头B唯一排第 2', startRate: 3.5, endRate: 3, probeAStartRate: 2.5, probeAEndRate: 3, probeBStartRate: 3.5, probeBEndRate: 3, probeCStartRate: 3.5, probeCEndRate: 4, contribution: 0.40625 },
    { index: 3, startBoundaryIndex: 3, endBoundaryIndex: 4, startTime: 30, endTime: 37.5, durationSeconds: 7.5, source: 'probeA', sourceReason: '探头A/B并列低值，按固定 A→B→C 顺序由探头A贡献中位值', startRate: 3, endRate: 3.5, probeAStartRate: 3, probeAEndRate: 3.5, probeBStartRate: 3, probeBEndRate: 2.5, probeCStartRate: 4, probeCEndRate: 3.5, contribution: 0.40625 },
    { index: 4, startBoundaryIndex: 4, endBoundaryIndex: 5, startTime: 37.5, endTime: 60, durationSeconds: 22.5, source: 'probeC', sourceReason: '探头C唯一排第 2', startRate: 3.5, endRate: 2, probeAStartRate: 3.5, probeAEndRate: 5, probeBStartRate: 2.5, probeBEndRate: 1, probeCStartRate: 3.5, probeCEndRate: 2, contribution: 1.03125 },
  ],
};

function mockFetchResponse(status, body) {
  fetch.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

const singlePassing = {
  f0: 3.0,
  threshold: 3.0,
  passed: true,
  shortfall: null,
  segments: [
    { index: 1, startTime: 0, endTime: 60, startTemperature: 121.1, endTemperature: 121.1, startRate: 1, endRate: 1, durationSeconds: 60, contribution: 1 },
    { index: 2, startTime: 60, endTime: 120, startTemperature: 121.1, endTemperature: 121.1, startRate: 1, endRate: 1, durationSeconds: 60, contribution: 1 },
    { index: 3, startTime: 120, endTime: 180, startTemperature: 121.1, endTemperature: 121.1, startRate: 1, endRate: 1, durationSeconds: 60, contribution: 1 },
  ],
};

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openDual(user) {
  await user.click(screen.getByRole('tab', { name: '双探头保守复核' }));
}

async function enableTriple(user) {
  await user.click(screen.getByTestId('triple-mode-toggle'));
}

describe('双探头录入', () => {
  it('并列渲染两支探头的录入表，默认各自从 0 秒开始、结束于同一秒', async () => {
    const user = userEvent.setup();
    render(<App />);
    await openDual(user);

    expect(screen.getByLabelText('探头A 时间 第1行')).toHaveValue('0');
    expect(screen.getByLabelText('探头B 时间 第1行')).toHaveValue('0');
    const aTimes = screen
      .getAllByLabelText(/^探头A 时间/)
      .map((el) => el.value);
    const bTimes = screen
      .getAllByLabelText(/^探头B 时间/)
      .map((el) => el.value);
    expect(aTimes.at(-1)).toBe(bTimes.at(-1));
  });

  it('提交体分别携带 probeA/probeB 的采样点', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, dualCrossingResponse);
    render(<App />);
    await openDual(user);
    await user.click(screen.getByTestId('dual-submit'));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/lethality/dual');
    const body = JSON.parse(options.body);
    expect(body.probeA.points).toHaveLength(5);
    expect(body.probeB.points).toHaveLength(4);
    expect(body.probeA.points[0]).toEqual({ time: 0, temperature: 126.0 });
    expect(body.probeB.points.at(-1)).toEqual({ time: 120, temperature: 127.0 });
  });
});

describe('双探头结果展示：图形与明细同一响应', () => {
  it('展示保守结论、两探头总量与带来源的保守段明细', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, dualCrossingResponse);
    render(<App />);
    await openDual(user);
    await user.click(screen.getByTestId('dual-submit'));

    const conclusion = await screen.findByTestId('dual-conclusion');
    expect(conclusion).toHaveTextContent('不放行');
    expect(conclusion).toHaveTextContent('1.500000');

    const totals = screen.getByTestId('dual-totals');
    expect(totals).toHaveTextContent('探头A 总量 2.000000');
    expect(totals).toHaveTextContent('探头B 总量 2.000000');

    const panel = screen.getByLabelText('双探头保守复核结果');
    const rows = within(panel).getAllByRole('row');
    // 表头 + 2 保守段 + 合计
    expect(rows).toHaveLength(4);
    expect(rows[1]).toHaveTextContent('探头A');
    expect(rows[2]).toHaveTextContent('探头B');
    expect(rows[1]).toHaveTextContent('0.000 → 30.000');
    expect(rows[2]).toHaveTextContent('30.000 → 60.000');
    expect(screen.getByTestId('dual-total')).toHaveTextContent('1.500000');

    // 图形与表格共用同一响应：SVG 内含两段下包络粗线与一个换源交点
    const svg = screen.getByLabelText('双探头致死速率曲线与保守下包络');
    expect(within(svg).getAllByText(/./).length).toBeGreaterThan(0);
  });

  it('未舍入总量低于门槛但四舍五入为 3.00 时仍判不放行', async () => {
    const user = userEvent.setup();
    const boundary = {
      ...dualCrossingResponse,
      conservativeUnrounded: 2.99996,
      conservativeF0: 3.0,
      passed: false,
      shortfall: 0.00004,
    };
    mockFetchResponse(200, boundary);
    render(<App />);
    await openDual(user);
    await user.click(screen.getByTestId('dual-submit'));

    const conclusion = await screen.findByTestId('dual-conclusion');
    expect(conclusion).toHaveTextContent('不放行');
    expect(conclusion).toHaveTextContent('2.999960');
    expect(conclusion).toHaveTextContent('展示口径 3.00');
    expect(conclusion).toHaveTextContent('尚差 0.000040');
  });
});

describe('双探头失败隔离', () => {
  it('双探头 422 按探头与行展示，并清除双探头结果', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, dualCrossingResponse);
    render(<App />);
    await openDual(user);
    await user.click(screen.getByTestId('dual-submit'));
    expect(await screen.findByTestId('dual-conclusion')).toBeInTheDocument();

    mockFetchResponse(422, {
      detail: {
        message: '采样数据校验失败',
        errors: [
          { row: 2, field: 'time', probe: 'probeB', message: '相邻采样间隔不得超过 60 秒' },
        ],
      },
    });
    await user.click(screen.getByTestId('dual-submit'));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('探头B');
    expect(alert).toHaveTextContent('第 2 行');
    expect(screen.queryByTestId('dual-conclusion')).not.toBeInTheDocument();
  });

  it('双探头请求失败不影响已经显示的单探头结论', async () => {
    const user = userEvent.setup();
    // 先在单探头模式得到放行结论
    mockFetchResponse(200, singlePassing);
    render(<App />);
    await user.click(screen.getByRole('button', { name: '计算致死量' }));
    expect(await screen.findByTestId('conclusion')).toHaveTextContent('放行');

    // 切到双探头并触发失败（网络异常）
    await openDual(user);
    fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await user.click(screen.getByTestId('dual-submit'));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('无法连接服务器');

    // 切回单探头：原结论仍在，且未再发请求
    await user.click(screen.getByRole('tab', { name: '单探头复核' }));
    expect(screen.getByTestId('conclusion')).toHaveTextContent('放行');
  });

  it('跨探头结束时刻不一致时展示整体错误', async () => {
    const user = userEvent.setup();
    mockFetchResponse(422, {
      detail: {
        message: '采样数据校验失败',
        errors: [
          { row: null, field: 'probe', probe: null, message: '两支探头必须结束于同一秒（探头A结束于 120 秒，探头B结束于 60 秒）' },
        ],
      },
    });
    render(<App />);
    await openDual(user);
    await user.click(screen.getByTestId('dual-submit'));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('两支探头必须结束于同一秒');
  });
});

describe('三探头可选模式', () => {
  it('启用后渲染探头C，提交到 /api/lethality/triple', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, tripleResponse);
    render(<App />);
    await openDual(user);
    await enableTriple(user);

    expect(screen.getByLabelText('探头C 时间 第1行')).toBeInTheDocument();
    await user.click(screen.getByTestId('dual-submit'));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/lethality/triple');
    const body = JSON.parse(options.body);
    expect(body.probeC.points).toHaveLength(4);
  });

  it('摘要、共享边界表、片段表和图形使用同一组边界和来源', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, tripleResponse);
    render(<App />);
    await openDual(user);
    await enableTriple(user);
    await user.click(screen.getByTestId('dual-submit'));

    const conclusion = await screen.findByTestId('dual-conclusion');
    expect(conclusion).toHaveTextContent('三探头中位 F₀ = 2.875000');
    expect(conclusion).toHaveTextContent('展示口径 2.88');

    const boundaryRows = within(screen.getByTestId('triple-boundaries')).getAllByRole('row');
    expect(boundaryRows).toHaveLength(6);
    expect(boundaryRows[2]).toHaveTextContent('22.500000');
    expect(boundaryRows[2]).toHaveTextContent('探头B/探头C');

    const panel = screen.getByLabelText('三探头中位复核结果');
    const segmentRows = within(panel).getAllByRole('row').slice(-6);
    expect(segmentRows).toHaveLength(6); // 片段表头 + 4 段 + 合计
    const dataRows = segmentRows.slice(1, 5);
    expect(dataRows.map((row) => row.dataset.source)).toEqual([
      'probeC',
      'probeB',
      'probeA',
      'probeC',
    ]);
    expect(dataRows[0]).toHaveTextContent('0.000 → 22.500');
    expect(dataRows[1]).toHaveTextContent('22.500 → 30.000');
    expect(dataRows[2]).toHaveTextContent('固定 A→B→C');
    expect(screen.getByTestId('dual-total')).toHaveTextContent('2.875000');

    const svg = screen.getByLabelText('三探头致死速率曲线与逐刻中位值');
    expect(svg).toBeInTheDocument();
    const chartSegments = svg.querySelectorAll('[data-testid^="envelope-segment-"]');
    expect(chartSegments).toHaveLength(4);
    expect([...chartSegments].map((line) => line.dataset.segmentIndex)).toEqual([
      '1',
      '2',
      '3',
      '4',
    ]);
    expect([...chartSegments].map((line) => line.getAttribute('stroke'))).toEqual([
      '#0b7a3b',
      '#c05a00',
      '#0b6bcb',
      '#0b7a3b',
    ]);
    // 图表粗线的起止共享边界编号与片段表完全一致，内部共享边界为 22.5/30/37.5。
    expect(chartSegments[1].dataset.startBoundaryIndex).toBe('2');
    expect(chartSegments[1].dataset.endBoundaryIndex).toBe('3');
    expect(svg.querySelectorAll('[data-testid^="shared-boundary-"]')).toHaveLength(3);

    const contributions = dataRows.map((row) =>
      Number(row.querySelector('td:last-child').textContent),
    );
    expect(contributions.reduce((a, b) => a + b, 0)).toBeCloseTo(2.875, 6);
  });

  it('第三路非法时拒绝本次分析且保留上一份有效三探头报告', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, tripleResponse);
    render(<App />);
    await openDual(user);
    await enableTriple(user);
    await user.click(screen.getByTestId('dual-submit'));
    expect(await screen.findByTestId('dual-conclusion')).toBeInTheDocument();

    mockFetchResponse(422, {
      detail: {
        message: '采样数据校验失败',
        errors: [
          { row: 2, field: 'time', probe: 'probeC', message: '相邻采样间隔不得超过 60 秒' },
        ],
      },
    });
    await user.click(screen.getByTestId('dual-submit'));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('保留上一份有效三探头报告');
    expect(alert).toHaveTextContent('探头C');
    expect(screen.getByTestId('dual-conclusion')).toHaveTextContent('2.875000');
    expect(screen.getByTestId('triple-boundaries')).toBeInTheDocument();
  });
});
