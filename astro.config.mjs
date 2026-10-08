import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import { readFileSync } from 'node:fs';
const data = JSON.parse(readFileSync(new URL('./public/data/intelligence.json', import.meta.url), 'utf8'));
const samplePaths = data.projects.filter((p) => p.sample).map((p) => `/projects/${p.project_id}/`);
const site = process.env.SITE_URL || 'http://localhost:4321';
const base = process.env.BASE_PATH || '/';
export default defineConfig({
  site,
  base,
  output: 'static',
  trailingSlash: 'always',
  integrations: [
    sitemap({ filter: (url) => !url.includes('/samples/') && !samplePaths.some((p) => url.endsWith(p)) }),
  ],
});
