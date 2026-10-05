/** 与后端 /api/lethality、/api/lethality/dual 的真实 HTTP 交互。 */

export class ApiError extends Error {
  constructor(errors) {
    super('采样数据校验失败');
    this.name = 'ApiError';
    this.errors = errors;
  }
}

async function postJson(url, body) {
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError([
      { row: null, field: null, probe: null, message: '无法连接服务器，请稍后重试' },
    ]);
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const errors = data?.detail?.errors ?? [
      { row: null, field: null, probe: null, message: `服务器返回错误（HTTP ${response.status}）` },
    ];
    throw new ApiError(errors);
  }
  return data;
}

export async function calculateLethality(points) {
  return postJson('/api/lethality', { points });
}

export async function calculateDualLethality(probeAPoints, probeBPoints) {
  return postJson('/api/lethality/dual', {
    probeA: { points: probeAPoints },
    probeB: { points: probeBPoints },
  });
}

export async function calculateTripleLethality(probeAPoints, probeBPoints, probeCPoints) {
  return postJson('/api/lethality/triple', {
    probeA: { points: probeAPoints },
    probeB: { points: probeBPoints },
    probeC: { points: probeCPoints },
  });
}
