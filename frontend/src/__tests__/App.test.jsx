import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App.jsx';

const passingResponse = {
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

const failingResponse = {
  f0: 2.98,
  threshold: 3.0,
  passed: false,
  shortfall: 0.02,
  segments: [
    { index: 1, startTime: 0, endTime: 60, startTemperature: 121.1, endTemperature: 121.1, startRate: 1, endRate: 1, durationSeconds: 60, contribution: 1 },
    { index: 2, startTime: 60, endTime: 120, startTemperature: 121.1, endTemperature: 121.1, startRate: 1, endRate: 1, durationSeconds: 60, contribution: 1 },
    { index: 3, startTime: 120, endTime: 179, startTemperature: 121.1, endTemperature: 121.1, startRate: 1, endRate: 1, durationSeconds: 59, contribution: 0.983333 },
  ],
};

function mockFetchResponse(status, body) {
  fetch.mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('采样录入表格', () => {
  it('默认渲染 4 行采样', () => {
    render(<App />);
    expect(screen.getByLabelText('时间 第1行')).toHaveValue('0');
    expect(screen.getByLabelText('时间 第4行')).toHaveValue('180');
    expect(screen.getAllByRole('button', { name: /^删除/ })).toHaveLength(4);
  });

  it('点击“添加采样行”追加一行并自动建议下一时刻', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: '添加采样行' }));
    expect(screen.getByLabelText('时间 第5行')).toHaveValue('210');
    expect(screen.getByLabelText('温度 第5行')).toHaveValue('121.1');
  });

  it('点击“删除”移除对应行', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByLabelText('删除 第2行'));
    expect(screen.queryByLabelText('时间 第4行')).not.toBeInTheDocument();
    expect(screen.getByLabelText('时间 第2行')).toHaveValue('120');
  });

  it('仅剩 2 行时禁止继续删除', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByLabelText('删除 第4行'));
    await user.click(screen.getByLabelText('删除 第3行'));
    expect(screen.getByLabelText('删除 第1行')).toBeDisabled();
    expect(screen.getByLabelText('删除 第2行')).toBeDisabled();
  });

  it('编辑输入更新行内容', async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByLabelText('温度 第1行');
    await user.clear(input);
    await user.type(input, '118.5');
    expect(input).toHaveValue('118.5');
  });
});

describe('计算与结论展示', () => {
  it('达标批次显示放行、F₀ 与逐段贡献', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, passingResponse);
    render(<App />);
    await user.click(screen.getByRole('button', { name: '计算致死量' }));

    const conclusion = await screen.findByTestId('conclusion');
    expect(conclusion).toHaveTextContent('放行');
    expect(conclusion).toHaveTextContent('3.00');
    expect(screen.getByTestId('f0-total')).toHaveTextContent('3.00');
    const segmentRows = within(
      screen.getByLabelText('计算结果'),
    ).getAllByRole('row');
    // 表头 1 行 + 3 段 + 合计 1 行
    expect(segmentRows).toHaveLength(5);
  });

  it('不足量批次显示距门槛的差额', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, failingResponse);
    render(<App />);
    await user.click(screen.getByRole('button', { name: '计算致死量' }));

    const conclusion = await screen.findByTestId('conclusion');
    expect(conclusion).toHaveTextContent('不放行');
    expect(conclusion).toHaveTextContent('2.98');
    expect(conclusion).toHaveTextContent('尚差 0.02 min');
  });

  it('微小段贡献完整展示，可据分段复算合计', async () => {
    // 100 °C 下两个 30 s 段各约 0.003881 min：接口返回未舍入段贡献，
    // 页面须显示 0.003881 而非 0.000000，合计为 0.01
    const smallSegmentsResponse = {
      f0: 0.01,
      threshold: 3.0,
      passed: false,
      shortfall: 2.99,
      segments: [
        { index: 1, startTime: 0, endTime: 30, startTemperature: 100, endTemperature: 100, startRate: 0.007762, endRate: 0.007762, durationSeconds: 30, contribution: 0.00388123558 },
        { index: 2, startTime: 30, endTime: 60, startTemperature: 100, endTemperature: 100, startRate: 0.007762, endRate: 0.007762, durationSeconds: 30, contribution: 0.00388123558 },
      ],
    };
    const user = userEvent.setup();
    mockFetchResponse(200, smallSegmentsResponse);
    render(<App />);
    await user.click(screen.getByRole('button', { name: '计算致死量' }));

    await screen.findByTestId('conclusion');
    const rows = within(screen.getByLabelText('计算结果')).getAllByRole('row');
    // 表头 1 行 + 2 段 + 合计 1 行
    expect(rows).toHaveLength(4);
    expect(rows[1]).toHaveTextContent('0.003881');
    expect(rows[2]).toHaveTextContent('0.003881');
    expect(screen.getByTestId('f0-total')).toHaveTextContent('0.01');
  });

  it('临界批次 F₀ 四舍五入为 3.00 时判放行且不显示差额', async () => {
    const boundaryResponse = {
      f0: 3.0,
      threshold: 3.0,
      passed: true,
      shortfall: null,
      segments: [
        { index: 1, startTime: 0, endTime: 60, startTemperature: 125.865, endTemperature: 125.865, startRate: 2.995712, endRate: 2.995712, durationSeconds: 60, contribution: 2.995711592 },
      ],
    };
    const user = userEvent.setup();
    mockFetchResponse(200, boundaryResponse);
    render(<App />);
    await user.click(screen.getByRole('button', { name: '计算致死量' }));

    const conclusion = await screen.findByTestId('conclusion');
    expect(conclusion).toHaveTextContent('放行');
    expect(conclusion).not.toHaveTextContent('尚差');
  });

  it('非法行使整次请求失败：展示行与字段并清除旧结论', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, passingResponse);
    render(<App />);
    await user.click(screen.getByRole('button', { name: '计算致死量' }));
    expect(await screen.findByTestId('conclusion')).toBeInTheDocument();

    mockFetchResponse(422, {
      detail: {
        message: '采样数据校验失败，整次请求已拒绝',
        errors: [
          { row: 2, field: 'temperature', message: '温度须在 100.0 至 140.0 °C 之间' },
        ],
      },
    });
    await user.click(screen.getByRole('button', { name: '计算致死量' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('第 2 行 · 温度(°C)');
    expect(alert).toHaveTextContent('温度须在 100.0 至 140.0 °C 之间');
    expect(screen.queryByTestId('conclusion')).not.toBeInTheDocument();
  });

  it('网络异常时提示并清除旧结论', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, passingResponse);
    render(<App />);
    await user.click(screen.getByRole('button', { name: '计算致死量' }));
    expect(await screen.findByTestId('conclusion')).toBeInTheDocument();

    fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await user.click(screen.getByRole('button', { name: '计算致死量' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('无法连接服务器');
    expect(screen.queryByTestId('conclusion')).not.toBeInTheDocument();
  });

  it('提交体将录入行转换为数值采样点', async () => {
    const user = userEvent.setup();
    mockFetchResponse(200, passingResponse);
    render(<App />);
    await user.click(screen.getByRole('button', { name: '计算致死量' }));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/lethality');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({
      points: [
        { time: 0, temperature: 121.1 },
        { time: 60, temperature: 121.1 },
        { time: 120, temperature: 121.1 },
        { time: 180, temperature: 121.1 },
      ],
    });
  });
});
