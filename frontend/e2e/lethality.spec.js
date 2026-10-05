import { expect, test } from '@playwright/test';

// 真实联调：页面经 nginx 代理访问 FastAPI，无任何 mock。
test.describe('致死量复核联调', () => {
  test('默认达标批次显示放行与逐段贡献', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '计算致死量' }).click();

    const conclusion = page.getByTestId('conclusion');
    await expect(conclusion).toContainText('放行');
    await expect(conclusion).toContainText('3.00');
    await expect(page.getByTestId('f0-total')).toHaveText('3.00');
    await expect(page.locator('.segments tbody tr')).toHaveCount(3);
  });

  test('不足量批次显示距门槛差额', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('时间 第4行').fill('179');
    await page.getByRole('button', { name: '计算致死量' }).click();

    const conclusion = page.getByTestId('conclusion');
    await expect(conclusion).toContainText('不放行');
    await expect(conclusion).toContainText('2.98');
    await expect(conclusion).toContainText('尚差 0.02 min');
  });

  test('非法行使整次请求失败并清除旧结论', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '计算致死量' }).click();
    await expect(page.getByTestId('conclusion')).toBeVisible();

    await page.getByLabel('温度 第2行').fill('99');
    await page.getByRole('button', { name: '计算致死量' }).click();

    const alert = page.getByRole('alert');
    await expect(alert).toContainText('第 2 行');
    await expect(alert).toContainText('温度');
    await expect(page.getByTestId('conclusion')).toHaveCount(0);
  });

  test('间隔超过 60 秒被服务端拒绝并定位行', async ({ page }) => {
    await page.goto('/');
    await page.getByLabel('时间 第2行').fill('61');
    await page.getByRole('button', { name: '计算致死量' }).click();

    const alert = page.getByRole('alert');
    await expect(alert).toContainText('第 2 行');
    await expect(alert).toContainText('60 秒');
  });

  test('可增删采样行并提交计算', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '添加采样行' }).click();
    await expect(page.getByLabel('时间 第5行')).toHaveValue('210');

    await page.getByLabel('删除 第5行').click();
    await expect(page.getByLabel('时间 第5行')).toHaveCount(0);

    await page.getByRole('button', { name: '计算致死量' }).click();
    await expect(page.getByTestId('conclusion')).toContainText('放行');
  });
});
