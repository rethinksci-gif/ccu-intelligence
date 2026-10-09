import { defineCollection } from 'astro:content';
import { z } from 'astro/zod';
import { glob } from 'astro/loaders';
const issues = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/issues' }),
  schema: z
    .object({
      title: z.string(),
      issue_number: z.number(),
      publication_date: z.coerce.date().nullable(),
      coverage_start: z.coerce.date(),
      coverage_end: z.coerce.date(),
      featured_topics: z.array(z.string()),
      source_count: z.number(),
      editorial_status: z.enum(['draft', 'sample', 'published', 'research_published']),
      last_updated: z.coerce.date(),
      sample: z.boolean().default(false),
      publication_authorization: z.string().optional(),
      reviewer: z.string().nullable().optional(),
      reviewed_at: z.coerce.date().nullable().optional(),
    })
    .refine(
      (d) =>
        d.editorial_status !== 'published' ||
        (!d.sample && !!d.publication_date && !!d.reviewer && !!d.reviewed_at),
      'Published content must be non-sample and human reviewed',
    )
    .refine(
      (d) =>
        d.editorial_status !== 'research_published' ||
        (!d.sample && !!d.publication_date && !!d.publication_authorization?.trim()),
      'Research publication requires explicit authorization and a publication date',
    ),
});
const learning = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/learning' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    category: z.string(),
    order: z.number(),
    updated: z.coerce.date(),
  }),
});
export const collections = { issues, learning };
