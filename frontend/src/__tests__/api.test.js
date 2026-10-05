import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, calculateLethality } from '../api.js';

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('calculateLethality', () => {
  it('以 POST JSON 调用 /api/lethality 并返回结果', async () => {
    const payload = { f0: 3.0, threshold: 3.0, passed: true, shortfall: null, segments: [] };
    fetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => payload });

    const result = await calculateLethality([
      { time: 0, temperature: 121.1 },
      { time: 60, temperature: 121.1 },
    ]);

    expect(result).toEqual(payload);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe('/api/lethality');
    expect(options.method).toBe('POST');
    expect(options.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(options.body).points).toHaveLength(2);
  });

  it('422 时抛出携带行与字段的 ApiError', async () => {
    const errors = [{ row: 2, field: 'time', message: '相邻采样间隔不得超过 60 秒' }];
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ detail: { message: '采样数据校验失败', errors } }),
    });

    const error = await calculateLethality([]).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.errors).toEqual(errors);
  });

  it('网络异常时抛出带提示的 ApiError', async () => {
    fetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const error = await calculateLethality([]).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.errors[0].message).toContain('无法连接服务器');
  });

  it('非 JSON 错误响应时给出状态码提示', async () => {
    fetch.mockResolvedValueOnce({ ok: false, status: 502, json: async () => null });
    const error = await calculateLethality([]).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.errors[0].message).toContain('502');
  });
});
