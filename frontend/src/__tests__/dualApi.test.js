import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, calculateDualLethality, calculateTripleLethality } from '../api.js';

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const dualResponse = {
  threshold: 3.0,
  probeA: {
    probe: 'probeA',
    points: [
      { time: 0, temperature: 121.1, rate: 1 },
      { time: 60, temperature: 121.1, rate: 1 },
    ],
    totalUnrounded: 1.0,
    f0: 1.0,
  },
  probeB: {
    probe: 'probeB',
    points: [
      { time: 0, temperature: 121.1, rate: 1 },
      { time: 60, temperature: 121.1, rate: 1 },
    ],
    totalUnrounded: 1.0,
    f0: 1.0,
  },
  probeATotalUnrounded: 1.0,
  probeBTotalUnrounded: 1.0,
  probeAF0: 1.0,
  probeBF0: 1.0,
  conservativeUnrounded: 1.0,
  conservativeF0: 1.0,
  passed: false,
  shortfall: 2.0,
  segments: [
    {
      index: 1,
      startTime: 0,
      endTime: 60,
      durationSeconds: 60,
      source: 'both',
      startRate: 1,
      endRate: 1,
      probeAStartRate: 1,
      probeAEndRate: 1,
      probeBStartRate: 1,
      probeBEndRate: 1,
      contribution: 1.0,
    },
  ],
};

describe('calculateDualLethality', () => {
  it('以 POST JSON 调用 /api/lethality/dual 并返回结果', async () => {
    fetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => dualResponse });

    const result = await calculateDualLethality(
      [{ time: 0, temperature: 121.1 }],
      [{ time: 0, temperature: 121.1 }],
    );

    expect(result).toEqual(dualResponse);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/lethality/dual');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({
      probeA: { points: [{ time: 0, temperature: 121.1 }] },
      probeB: { points: [{ time: 0, temperature: 121.1 }] },
    });
  });

  it('422 时抛出携带探头、行与字段的 ApiError', async () => {
    const errors = [
      { row: 2, field: 'time', probe: 'probeB', message: '相邻采样间隔不得超过 60 秒' },
    ];
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ detail: { message: '采样数据校验失败', errors } }),
    });

    const error = await calculateDualLethality([], []).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.errors).toEqual(errors);
  });

  it('网络异常时抛出带提示的 ApiError', async () => {
    fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const error = await calculateDualLethality([], []).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.errors[0].message).toContain('无法连接服务器');
  });
});

describe('calculateTripleLethality', () => {
  it('以 POST JSON 调用 /api/lethality/triple 并携带三支探头', async () => {
    const tripleResponse = {
      mode: 'triple',
      probeA: { points: [] },
      probeB: { points: [] },
      probeC: { points: [] },
      medianUnrounded: 3,
      segments: [],
      boundaries: [],
    };
    fetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => tripleResponse });

    const result = await calculateTripleLethality(
      [{ time: 0, temperature: 121.1 }],
      [{ time: 0, temperature: 121.2 }],
      [{ time: 0, temperature: 121.3 }],
    );

    expect(result).toEqual(tripleResponse);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/lethality/triple');
    expect(JSON.parse(options.body)).toEqual({
      probeA: { points: [{ time: 0, temperature: 121.1 }] },
      probeB: { points: [{ time: 0, temperature: 121.2 }] },
      probeC: { points: [{ time: 0, temperature: 121.3 }] },
    });
  });
});
