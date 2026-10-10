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
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(2);
  await expect(page.locator('#project-count')).toContainText('2 projects');
  await page.getByLabel('Search projects').fill('no such project');
  await expect(page.locator('#project-empty')).toBeVisible();
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(9);
  await page.getByLabel('Data scope').selectOption('sample');
  await expect(page.locator('#project-empty')).toBeVisible();
});

test('capacity filter respects comparable groups', async ({ page }) => {
  await page.goto('projects/');
  await expect(page.getByLabel('Minimum announced capacity')).toBeDisabled();
  await page.getByLabel('Comparable capacity group').selectOption('product_output|Methanol|t/year');
  await page.getByLabel('Minimum announced capacity').fill('50000');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(2);
  await page.getByLabel('Minimum announced capacity').fill('200000');
  await expect(page.locator('#project-empty')).toBeVisible();
});

test('technology atlas groups pathways and links tracked projects', async ({ page }) => {
  await page.goto('technologies/');
  await expect(page.locator('.atlas-card')).toHaveCount(10);
  for (const stage of ['Capture & supply', 'Conversion', 'Mineralization']) {
    await expect(page.getByRole('heading', { level: 2, name: stage, exact: true })).toBeVisible();
  }
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits).toBe(true);
  await page.getByRole('link', { name: 'CO₂ to methanol', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Where the carbon goes' })).toBeVisible();
  await page.getByRole('link', { name: 'Kassø e-methanol facility' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Kassø');
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
  await expect(page.locator('#issue-count')).toHaveText('1 published issue shown');
  await expect(page.getByRole('link', { name: 'Read the sample issue' })).toHaveCount(0);
  expect((await request.get('samples/issue/')).status()).toBe(404);
  expect((await request.get('projects/northport-methanol/')).status()).toBe(404);
  const response = await request.get('rss.xml');
  const feed = await response.text();
  expect(feed).toContain('<item>');
  expect(feed).toContain('Research edition; full editorial review incomplete');
  const data = await (await request.get('data/intelligence.json')).json();
  expect(data.projects).toHaveLength(9);
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
  await expect(links).toHaveCount(9);
  const name = await links.first().innerText();
  await links.first().click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(name);
  await context.close();
});

test('filters survive sharing, reload and return from details', async ({ page }) => {
  await page.goto('projects/?region=Europe&scope=live');
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('Europe');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(5);
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
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(9);
  await expect(page.getByLabel('Minimum announced capacity')).toBeDisabled();
});

test('invalid URL filters fall back and search ignores surrounding spaces', async ({ page }) => {
  await page.goto('projects/?region=invalid&scope=invalid&minCapacity=-1&ref=shared');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(9);
  await expect(page.getByRole('combobox', { name: 'Region', exact: true })).toHaveValue('');
  await expect(page.getByLabel('Minimum announced capacity')).toHaveValue('');
  await page.getByLabel('Search projects').fill('  China  ');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(2);
  await expect(page).toHaveURL(/ref=shared/);
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page).toHaveURL(/projects\/\?ref=shared$/);
});

test('published research edition is reachable and accurately labelled', async ({ page }) => {
  await page.goto('./');
  await page.getByRole('link', { name: 'Read the latest issue' }).click();
  await expect(page).toHaveURL(/issues\/issue-001-research-2026-10-09\/$/);
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Offtake Momentum');
  await expect(page.locator('.prose-title')).toContainText('Full editorial review incomplete');
  await expect(page.locator('.prose-title')).not.toContainText('Reviewed by');
  await expect(page.locator('article')).toContainText('RESEARCH EDITION');
  await expect(page.locator('article')).not.toContainText('not published');
  await page.getByRole('link', { name: 'All issues', exact: true }).click();
  await expect(page.locator('.issue-card')).toHaveCount(1);
  await expect(page.locator('.issue-card')).toContainText('Research edition');
});

test('issue contents links reach real sections on desktop and mobile', async ({ page }) => {
  await page.goto('issues/issue-001-research-2026-10-09/');
  await page.screenshot({ path: test.info().outputPath('issue.png') });
  const contents = page.getByRole('navigation', { name: 'Issue contents' });
  const links = contents.locator('ol a');
  expect(await links.count()).toBeGreaterThan(5);
  for (const link of await links.all()) {
    const hash = await link.getAttribute('href');
    expect(await page.locator(`[id="${hash!.slice(1)}"]`).count()).toBe(1);
  }
  await contents.getByRole('link', { name: 'What to watch', exact: true }).click();
  await expect(page).toHaveURL(/#what-to-watch$/);
  await expect(page.locator('.prose-title')).toContainText('2026-09-25 – 2026-10-08 (UTC)');
  await expect(
    page.getByRole('link', { name: 'Biweekly issues', exact: true, includeHidden: true }),
  ).toHaveAttribute('aria-current', 'location');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.emulateMedia({ media: 'print' });
  await expect(contents).not.toBeVisible();
});

test('archive filters handle no results and survive reload and reset', async ({ page }) => {
  await page.goto('issues/?q=missing-story&ref=shared');
  await expect(page.locator('#issue-empty')).toContainText('No issues match your search');
  await expect(page.locator('.issue-card:visible')).toHaveCount(0);
  await page.getByRole('searchbox', { name: 'Search the archive' }).fill('  Offtake  ');
  await expect(page.locator('.issue-card:visible')).toHaveCount(1);
  await expect(page).toHaveURL(/q=Offtake/);
  await page.reload();
  await expect(page.getByRole('searchbox', { name: 'Search the archive' })).toHaveValue('Offtake');
  await page.getByRole('button', { name: 'Reset', exact: true }).click();
  await expect(page).toHaveURL(/issues\/\?ref=shared$/);
  await expect(page.locator('.issue-card:visible')).toHaveCount(1);
});

test('homepage sections and mobile navigation work without JavaScript', async ({
  browser,
  baseURL,
  isMobile,
}) => {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    baseURL,
    viewport: isMobile ? { width: 390, height: 844 } : { width: 1280, height: 800 },
  });
  const page = await context.newPage();
  await page.goto('./');
  await expect(page.getByRole('heading', { name: 'Inside the latest issue' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Executive signals' })).toHaveCount(0);
  const sectionLink = page.locator('.issue-sections a').first();
  await sectionLink.click();
  await expect(page).toHaveURL(/#key-takeaways$/);
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('link', { name: 'Biweekly issues' })
    .click();
  await expect(page.locator('.issue-card')).toHaveCount(1);
  await context.close();
});

test('project search handles accents, CO2 spelling and word order', async ({ page }) => {
  await page.goto('projects/');
  await page.getByLabel('Search projects').fill('CO2 Kasso');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(1);
  await expect(page.locator('tr[data-project]:visible')).toContainText('Kassø');
  await page.getByLabel('Search projects').fill('methanol Jiangsu');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(1);
  await expect(page.locator('tr[data-project]:visible')).toContainText('Sailboat');
});

test('project availability and verification filters persist and handle unknown values', async ({ page }) => {
  await page.goto('projects/?availability=no-capacity&verifiedSince=2026-10-09&confidence_level=medium');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(4);
  await expect(page.locator('tr[data-project]:visible')).toContainText([
    'POSEIDON',
    'Haru Oni',
    'AirPlant One',
    'HEIM Berlin',
  ]);
  await page.reload();
  await expect(page.getByLabel('Data availability')).toHaveValue('no-capacity');
  await page.getByLabel('Source checked on or after').fill('2100-01-01');
  await expect(page.locator('#project-empty')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Download filtered JSON' })).toBeDisabled();
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await page.getByLabel('Data availability').selectOption('output');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(0);
  await page.getByLabel('Data availability').selectOption('no-output');
  await expect(page.locator('tr[data-project]:visible')).toHaveCount(9);
});

test('capacity sorting and exported records respect the chosen comparable group', async ({ page }) => {
  const { readFile } = await import('node:fs/promises');
  await page.goto('projects/');
  await expect(page.locator('[name="sort"] option[value="capacity"]')).toHaveJSProperty('disabled', true);
  await page.screenshot({ path: test.info().outputPath('project-filters.png'), fullPage: true });
  await page.getByLabel('Comparable capacity group').selectOption('product_output|Methanol|t/year');
  await page.getByLabel('Sort by').selectOption('capacity');
  const visible = page.locator('tr[data-project]:visible');
  await expect(visible).toHaveCount(4);
  await expect(visible.first()).toContainText('Shunli');
  const pending = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download filtered JSON' }).click();
  const download = await pending;
  const result = JSON.parse(await readFile((await download.path())!, 'utf8'));
  expect(result.projects.map((p: { project_id: string }) => p.project_id)).toEqual([
    'shunli-methanol',
    'jiangsu-sailboat',
    'kasso-methanol',
    'george-olah',
  ]);
  expect(result.projects.every((p: { operational_capacity: null }) => p.operational_capacity === null)).toBe(
    true,
  );
  expect(result.filters.capacityGroup).toBe('product_output|Methanol|t/year');
  await page.getByLabel('Comparable capacity group').selectOption('');
  await expect(page.getByLabel('Sort by')).toHaveValue('');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
