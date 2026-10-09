import { getCollection } from 'astro:content';

export async function publicIssues() {
  return (
    await getCollection(
      'issues',
      ({ data }) => ['published', 'research_published'].includes(data.editorial_status) && !data.sample,
    )
  ).sort((a, b) => +b.data.publication_date! - +a.data.publication_date!);
}

export function readingMinutes(body = '') {
  const text = body
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/[#*_|>`~]/g, ' ');
  return Math.max(1, Math.ceil(text.trim().split(/\s+/).filter(Boolean).length / 220));
}

export function coverageLabel(start: Date, exclusiveEnd: Date) {
  const format = (date: Date) => date.toISOString().slice(0, 10);
  return `${format(start)} – ${format(new Date(+exclusiveEnd - 86400000))} (UTC)`;
}
