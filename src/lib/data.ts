import data from '../../public/data/intelligence.json';
export const { projects, companies, evidence, events, technologies, articles } = data;
export const companyName = (id: string) => companies.find((c) => c.company_id === id)?.name ?? id;
export const href = (path = '') =>
  `${import.meta.env.BASE_URL.replace(/\/$/, '')}/${path.replace(/^\//, '')}`;
export const quantity = (c: { value: number; unit: string; basis: string; substance: string } | null) =>
  c
    ? `${c.value.toLocaleString('en-US')} ${c.unit} · ${c.substance} (${c.basis.replaceAll('_', ' ')})`
    : 'Not reported';
export const label = (text: string) => text.toLowerCase().replaceAll('_', ' ');
