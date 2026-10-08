import { getCollection } from 'astro:content';
import type { APIRoute } from 'astro';
const escape = (s: string) =>
  s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
export const GET: APIRoute = async ({ site }) => {
  const base = import.meta.env.BASE_URL;
  const root = new URL(base, site ?? 'http://localhost:4321');
  const issues = (
    await getCollection('issues', ({ data }) => data.editorial_status === 'published' && !data.sample)
  ).sort((a, b) => +b.data.publication_date - +a.data.publication_date);
  const items = issues
    .map((i) => {
      const url = new URL(`issues/${i.id}/`, root);
      return `<item><title>${escape(i.data.title)}</title><link>${escape(String(url))}</link><guid>${escape(String(url))}</guid><pubDate>${i.data.publication_date.toUTCString()}</pubDate><description>${escape(i.data.featured_topics.join(' · '))}</description></item>`;
    })
    .join('');
  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>CCU Intelligence</title><link>${escape(String(root))}</link><description>Reviewed biweekly carbon capture and utilization intelligence.</description><language>en</language>${items}</channel></rss>`,
    { headers: { 'Content-Type': 'application/rss+xml; charset=utf-8' } },
  );
};
