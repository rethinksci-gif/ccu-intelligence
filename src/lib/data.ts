import data from '../../public/data/intelligence.json';
export const { projects, companies, evidence, technologies } = data;
// Empty production collections must retain their shape without publishing test fixtures.
interface Article {
  sample: boolean;
  editorial_status: string;
  review_required: boolean;
  title: string;
  canonical_url: string;
  publication_date: string | null;
  domains: string[];
  summary: string;
  industrial_implications: string | null;
  uncertainty: string;
}
interface ProjectEvent {
  project_id: string;
  reporting_date: string;
  event_date: string | null;
  event_type: string;
  description: string;
  previous_value: Record<string, unknown>;
  new_value: Record<string, unknown>;
}
export const articles: Article[] = data.articles;
export const events: ProjectEvent[] = data.events;
export const companyName = (id: string) => companies.find((c) => c.company_id === id)?.name ?? id;
export const href = (path = '') =>
  `${import.meta.env.BASE_URL.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
export const quantity = (c: { value: number; unit: string; basis: string; substance: string } | null) =>
  c
    ? `${c.value.toLocaleString('en-US')} ${c.unit} · ${c.substance} (${c.basis.replaceAll('_', ' ')})`
    : 'Not reported';
export const label = (text: string) => text.toLowerCase().replaceAll('_', ' ');
