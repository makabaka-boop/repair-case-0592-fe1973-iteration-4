import { expect, test } from '@playwright/test';

// 真实联调：页面经 nginx/vite 代理访问 FastAPI，无任何 mock。
test.describe('双探头保守复核联调', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.getByRole('tab', { name: '双探头保守复核' }).click();
  });

  test('默认双探头示例：下包络放行，图形与明细同源', async ({ page }) => {
    await page.getByTestId('dual-submit').click();

    const conclusion = page.getByTestId('dual-conclusion');
    await expect(conclusion).toContainText('放行');
    await expect(conclusion).toContainText('门槛');

    // 两探头各自总量与保守总量都展示；保守总量不是两份总量的较小值
    const totals = page.getByTestId('dual-totals');
    await expect(totals).toContainText('探头A 总量');
    await expect(totals).toContainText('探头B 总量');

    // 默认示例两条速率线在区间内部交换高低：来源段同时出现探头A与探头B
    const rows = page.locator('.dual-segments tbody tr');
    await expect(rows).not.toHaveCount(0);
    const sources = await rows.evaluateAll((els) =>
      els.map((el) => el.getAttribute('data-source')),
    );
    expect(sources).toContain('probeA');
    expect(sources).toContain('probeB');

    // 保守合计 = 各段贡献未舍入之和（同源响应，页面直接复算展示）
    await expect(page.getByTestId('dual-total')).toBeVisible();
    const contributions = await page
      .locator('.dual-segments tbody td:last-child')
      .allInnerTexts();
    const summed = contributions.reduce((acc, text) => acc + Number(text), 0);
    const shown = Number((await page.getByTestId('dual-total').innerText()));
    expect(Math.abs(summed - shown)).toBeLessThan(1e-5);

    // 图形渲染两探头折线与下包络
    await expect(
      page.getByLabel('双探头致死速率曲线与保守下包络'),
    ).toBeVisible();
  });

  test('两支探头完全相同时每段标注重合并与单探头结果一致', async ({ page }) => {
    // 把两支探头都改成相同的 121.1 °C 恒温 0/60/120/180 s（间隔校验要求 ≤60 s）。
    // 探头A 默认即 5 行、探头B 默认 4 行；统一删到 4 行后改值。
    for (const probe of ['探头A', '探头B']) {
      let count = await page.getByLabel(new RegExp(`^${probe} 时间`)).count();
      while (count > 4) {
        await page.getByLabel(`${probe} 删除 第3行`).click();
        count -= 1;
      }
      const times = ['0', '60', '120', '180'];
      for (let i = 1; i <= 4; i += 1) {
        await page.getByLabel(`${probe} 时间 第${i}行`).fill(times[i - 1]);
        await page.getByLabel(`${probe} 温度 第${i}行`).fill('121.1');
      }
    }

    await page.getByTestId('dual-submit').click();

    const conclusion = page.getByTestId('dual-conclusion');
    await expect(conclusion).toContainText('放行');
    await expect(conclusion).toContainText('3.000000');
    const sources = await page
      .locator('.dual-segments tbody tr')
      .evaluateAll((els) =>
        els.map((el) => el.getAttribute('data-source')),
      );
    expect(sources).toEqual(['both', 'both', 'both']);
  });

  test('探头B间隔超过60秒：按探头B第2行拒绝且清除本次比较', async ({ page }) => {
    await page.getByLabel('探头B 时间 第2行').fill('95'); // 默认第2行原为 45
    await page.getByTestId('dual-submit').click();

    const alert = page.getByRole('alert');
    await expect(alert).toContainText('探头B');
    await expect(alert).toContainText('第 2 行');
    await expect(alert).toContainText('60 秒');
    await expect(page.getByTestId('dual-conclusion')).toHaveCount(0);
  });

  test('两支探头结束秒不一致被拒绝', async ({ page }) => {
    await page.getByLabel('探头A 时间 第5行').fill('119');
    await page.getByTestId('dual-submit').click();

    const alert = page.getByRole('alert');
    await expect(alert).toContainText('结束于同一秒');
  });

  test('双探头失败后切回单探头，已显示的单探头结论不受影响', async ({ page }) => {
    // 先在单探头模式得到放行结论
    await page.getByRole('tab', { name: '单探头复核' }).click();
    await page.getByRole('button', { name: '计算致死量' }).click();
    await expect(page.getByTestId('conclusion')).toContainText('放行');

    // 双探头输入非法并提交：只清双探头比较
    await page.getByRole('tab', { name: '双探头保守复核' }).click();
    await page.getByLabel('探头B 时间 第2行').fill('95');
    await page.getByTestId('dual-submit').click();
    await expect(page.getByRole('alert')).toContainText('探头B');
    await expect(page.getByTestId('dual-conclusion')).toHaveCount(0);

    // 切回单探头：结论仍在
    await page.getByRole('tab', { name: '单探头复核' }).click();
    await expect(page.getByTestId('conclusion')).toContainText('放行');
  });
});
