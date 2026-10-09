import { publicIssues } from '../lib/issues';
import type { APIRoute } from 'astro';
const escape = (s: string) =>
  s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
export const GET: APIRoute = async ({ site }) => {
  const base = import.meta.env.BASE_URL;
  const root = new URL(base, site ?? 'http://localhost:4321');
  const issues = await publicIssues();
  const items = issues
    .map((i) => {
      const url = new URL(`issues/${i.id}/`, root);
      return `<item><title>${escape(i.data.title)}</title><link>${escape(String(url))}</link><guid>${escape(String(url))}</guid><pubDate>${i.data.publication_date!.toUTCString()}</pubDate><description>${escape((i.data.editorial_status === 'research_published' ? 'Research edition; full editorial review incomplete. ' : '') + i.data.featured_topics.join(' · '))}</description></item>`;
    })
    .join('');
  return new Response(
    `<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>CCU Intelligence</title><link>${escape(String(root))}</link><description>Biweekly carbon capture and utilization intelligence; research editions are labelled.</description><language>en</language>${items}</channel></rss>`,
    { headers: { 'Content-Type': 'application/rss+xml; charset=utf-8' } },
  );
};
