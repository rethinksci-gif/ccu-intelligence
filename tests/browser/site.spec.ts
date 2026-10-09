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
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(3);
  await page.getByLabel('Data scope').selectOption('sample');
  await expect(page.locator('#project-empty')).toBeVisible();
});

test('capacity filter respects comparable groups', async ({ page }) => {
  await page.goto('projects/');
  await expect(page.getByLabel('Minimum announced capacity')).toBeDisabled();
  await page.getByLabel('Comparable capacity group').selectOption('product_output|Methanol|t/year');
  await page.getByLabel('Minimum announced capacity').fill('50000');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(1);
  await page.getByLabel('Minimum announced capacity').fill('200000');
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

test('published output excludes fixtures and unapproved drafts', async ({ page, request }) => {
  await page.goto('issues/');
  await expect(page.locator('#issue-count')).toHaveText('0 published issues');
  await expect(page.getByRole('link', { name: 'Read the sample issue' })).toHaveCount(0);
  expect((await request.get('samples/issue/')).status()).toBe(404);
  expect((await request.get('projects/northport-methanol/')).status()).toBe(404);
  const response = await request.get('rss.xml');
  expect(await response.text()).not.toContain('<item>');
  const data = await (await request.get('data/intelligence.json')).json();
  expect(data.projects).toHaveLength(3);
  for (const records of Object.values(data) as { sample?: boolean }[][]) {
    expect(records.some((record) => record.sample)).toBe(false);
  }
});

test('real project shows attribution and leaves measured output unknown', async ({ page }) => {
  await page.goto('projects/kasso-methanol/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Kassø e-methanol facility');
  await expect(page.getByRole('link', { name: 'european-energy', exact: true })).toHaveAttribute(
    'href',
    /europeanenergy.com/,
  );
  await expect(
    page.getByText('Design capacity is not measured annual production.', { exact: false }),
  ).toBeVisible();
  await expect(
    page
      .locator('dt')
      .filter({ hasText: /^Operational capacity$/ })
      .locator('..'),
  ).toContainText('Not reported');
});

test('project names link to details without JavaScript', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, baseURL });
  const page = await context.newPage();
  await page.goto('projects/');
  const links = page.locator('tr[data-project] td:first-child a');
  await expect(links).toHaveCount(3);
  const name = await links.first().innerText();
  await links.first().click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
  await context.close();
});

test('filters survive sharing, reload and return from details', async ({ page }) => {
  await page.goto('projects/?region=Europe&scope=live');
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('Europe');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(2);
  await page.getByLabel('Comparable capacity group').selectOption('product_output|Methanol|t/year');
  await page.getByLabel('Minimum announced capacity').fill('10000');
  await expect(page).toHaveURL(/minCapacity=10000/);
  await page.reload();
  await expect(page.getByLabel('Minimum announced capacity')).toHaveValue('10000');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(1);
  await page.locator('tr[data-project]:visible td:first-child a').click();
  await page.goBack();
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('Europe');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(1);
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page).toHaveURL(/projects\/$/);
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(3);
  await expect(page.getByLabel('Minimum announced capacity')).toBeDisabled();
});

test('invalid URL filters fall back and search ignores surrounding spaces', async ({ page }) => {
  await page.goto('projects/?region=invalid&scope=invalid&minCapacity=-1&ref=shared');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(3);
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('');
  await expect(page.getByLabel('Minimum announced capacity')).toHaveValue('');
  await page.getByLabel('Search projects').fill('  China  ');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(1);
  await expect(page).toHaveURL(/ref=shared/);
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page).toHaveURL(/projects\/\?ref=shared$/);
});
