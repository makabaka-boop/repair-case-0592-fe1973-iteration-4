import { defineConfig } from '@playwright/test';

// 默认打向 docker compose 暴露的 Web 端口；可用 BASE_URL 或 WEB_PORT 覆盖。
const baseURL =
  process.env.BASE_URL || `http://localhost:${process.env.WEB_PORT || 8080}`;

export default defineConfig({
  testDir: './e2e',
  // 仅 *.spec.js 为联调用例，避免把同目录或相邻目录的非 spec 文件
  // （如 vitest 的 setup）误当作 Playwright 测试加载
  testMatch: '**/*.spec.js',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL,
  },
});
