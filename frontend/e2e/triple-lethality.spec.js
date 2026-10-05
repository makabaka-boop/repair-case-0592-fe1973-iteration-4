import { expect, test } from '@playwright/test';

test.describe('三探头中位复核联调', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.getByRole('tab', { name: '双探头保守复核' }).click();
    await page.getByTestId('triple-mode-toggle').check();
  });

  test('三探头模式：共享边界、片段表与图形一致，并给出每段来源理由', async ({ page }) => {
    // 使用手算样例：A 1→5、B 5→1、C 2→4→2；边界 0 / 22.5 / 30 / 37.5 / 60。
    const tempForRate = async (rate) => 121.1 + 10 * Math.log10(rate);
    const a = [
      { time: '0', temperature: String(await tempForRate(1)) },
      { time: '60', temperature: String(await tempForRate(5)) },
    ];
    const b = [
      { time: '0', temperature: String(await tempForRate(5)) },
      { time: '60', temperature: String(await tempForRate(1)) },
    ];
    const c = [
      { time: '0', temperature: String(await tempForRate(2)) },
      { time: '30', temperature: String(await tempForRate(4)) },
      { time: '60', temperature: String(await tempForRate(2)) },
    ];

    async function fillProbe(name, rows) {
      const editor = page
        .locator('.probe-editor', {
          has: page.getByRole('heading', { name, exact: true }),
        })
        .first();
      let count = await page.getByLabel(new RegExp(`^${name} 时间`)).count();
      while (count > rows.length) {
        await page.getByLabel(`${name} 删除 第${count}行`).click();
        count -= 1;
      }
      while (count < rows.length) {
        await editor.getByRole('button', { name: '添加采样行' }).click();
        count += 1;
      }
      for (let i = 1; i <= rows.length; i += 1) {
        await page.getByLabel(`${name} 时间 第${i}行`).fill(rows[i - 1].time);
        await page.getByLabel(`${name} 温度 第${i}行`).fill(rows[i - 1].temperature);
      }
    }

    await fillProbe('探头A', a);
    await fillProbe('探头B', b);
    await fillProbe('探头C', c);
    await page.getByTestId('dual-submit').click();

    const conclusion = page.getByTestId('dual-conclusion');
    await expect(conclusion).toContainText('三探头中位 F₀ = 2.875000');
    await expect(conclusion).toContainText('展示口径 2.88');

    const boundaryRows = page.locator('[data-testid="triple-boundaries"] tbody tr');
    await expect(boundaryRows).toHaveCount(5);
    await expect(boundaryRows.nth(1)).toContainText('22.500000');
    await expect(boundaryRows.nth(1)).toContainText('曲线交点');
    await expect(boundaryRows.nth(2)).toContainText('30.000000');
    await expect(boundaryRows.nth(2)).toContainText('采样节点');

    const segmentRows = page.locator('.dual-segments tbody tr');
    await expect(segmentRows).toHaveCount(4);
    const sources = await segmentRows.evaluateAll((els) =>
      els.map((el) => el.getAttribute('data-source')),
    );
    expect(sources).toEqual(['probeC', 'probeB', 'probeA', 'probeC']);

    const contributions = await page
      .locator('.dual-segments tbody td:last-child')
      .allInnerTexts();
    const summed = contributions.reduce((acc, text) => acc + Number(text), 0);
    const shown = Number(await page.getByTestId('dual-total').innerText());
    expect(Math.abs(summed - shown)).toBeLessThan(1e-5);
    expect(Math.abs(shown - 2.875)).toBeLessThan(1e-5);

    await expect(page.getByLabel('三探头致死速率曲线与逐刻中位值')).toBeVisible();
    await expect(segmentRows.nth(2)).toContainText('固定 A→B→C');
  });

  test('第三路非法时拒绝本次分析并保留上一份三探头报告', async ({ page }) => {
    await page.getByTestId('dual-submit').click();
    await expect(page.getByTestId('dual-conclusion')).toBeVisible();
    const previous = await page.getByTestId('dual-total').innerText();

    await page.getByLabel('探头C 时间 第2行').fill('95');
    await page.getByTestId('dual-submit').click();

    const alert = page.getByRole('alert');
    await expect(alert).toContainText('本次三探头分析被拒绝');
    await expect(alert).toContainText('探头C');
    await expect(alert).toContainText('第 2 行');
    await expect(page.getByTestId('dual-total')).toHaveText(previous);
  });
});
