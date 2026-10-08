import { test, expect } from '@playwright/test';

test('navigation is usable on desktop and mobile', async ({ page, isMobile }) => {
  await page.goto('./');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Industrial progress');
  await page.screenshot({ path: test.info().outputPath('home.png'), fullPage: true });
  if (isMobile) {
    await page.getByRole('button', { name: 'Menu', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Menu', exact: true })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  }
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('link', { name: 'Project tracker' })
    .click();
  await expect(page.getByRole('heading', { name: 'Project tracker', exact: true })).toBeVisible();
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits).toBe(true);
});

test('project filters and empty states', async ({ page }) => {
  await page.goto('projects/');
  await page.getByRole('combobox', { name: 'Region', exact: true }).selectOption('China');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(1);
  await expect(page.locator('#project-count')).toContainText('1 project');
  await page.getByLabel('Search projects').fill('no such project');
  await expect(page.locator('#project-empty')).toBeVisible();
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(4);
  await page.getByLabel('Data scope').selectOption('live');
  await expect(page.locator('#project-empty')).toBeVisible();
});

test('capacity filter respects comparable groups', async ({ page }) => {
  await page.goto('projects/');
  await expect(page.getByLabel('Minimum announced capacity')).toBeDisabled();
  await page.getByLabel('Comparable capacity group').selectOption('product_output|Methanol|t/year');
  await page.getByLabel('Minimum announced capacity').fill('10000');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(1);
  await page.getByLabel('Minimum announced capacity').fill('20000');
  await expect(page.locator('#project-empty')).toBeVisible();
});

test('calculator changes reproducibly and rejects invalid inputs', async ({ page }) => {
  await page.goto('technologies/co2-to-methanol/');
  await expect(page.locator('#cost')).toHaveText('$768/t');
  await page.getByLabel('Purchased H₂ · USD/kg').fill('6');
  await expect(page.locator('#cost')).toHaveText('$1364/t');
  await page.getByLabel('CO₂ utilization · %').fill('0');
  await expect(page.locator('#cost')).toHaveText('Invalid input');
  await page.getByRole('button', { name: 'Reset assumptions' }).click();
  await expect(page.locator('#cost')).toHaveText('$768/t');
});

test('sample issue excluded from published archive and feed', async ({ page, request }) => {
  await page.goto('issues/');
  await expect(page.locator('#issue-count')).toHaveText('0 published issues');
  await page.getByRole('link', { name: 'Read the sample issue' }).click();
  await expect(page.getByRole('heading', { name: 'Sample biweekly issue' })).toBeVisible();
  const response = await request.get('rss.xml');
  expect(await response.text()).not.toContain('<item>');
});

test('history preserves previous dates', async ({ page }) => {
  await page.goto('projects/eastbay-electrolysis/');
  await page.getByText('View historical change').click();
  await expect(page.locator('pre')).toContainText('2027');
  await expect(page.locator('pre')).toContainText('2029');
});
