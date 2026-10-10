# CCU Intelligence UI and typography

The site uses an editorial overview, a consistent set of data controls, and a constrained reading column for long articles. Existing Astro pages remain static; no component framework or remote font is required.

## References

Inspected on 2026-10-10. All three GitHub repositories were non-archived and reported pushes on 2026-10-09 through the GitHub API.

- [Astro Starlight](https://github.com/withastro/starlight), [documentation](https://starlight.astro.build/): readable article layouts, persistent contents navigation and progressive enhancement.
- [GitHub Primer CSS](https://github.com/primer/css), [UI patterns](https://primer.style/product/ui-patterns/): consistent borders, control spacing, navigation selection and responsive data presentation.
- [shadcn/ui](https://github.com/shadcn-ui/ui), [typography](https://ui.shadcn.com/docs/typeset): restrained surface styling and explicit heading, body and metadata hierarchy.

These inform the design; no source or package from these projects was copied or installed.

## Design decisions

- Retain the carbon research identity with a dark green lead story, warm neutral background, and teal links. System sans-serif supports controls and dense data; locally available Georgia gives overview and article titles an editorial hierarchy.
- The homepage prioritizes the latest issue, a methanol pathway illustration, live collection counts and a compact section index. Counts come from existing collections.
- Desktop project previews remain a table. On phones the same accessible table becomes stacked records with visible field labels, including the full evidence limitation.
- Article content is limited to 740px, with a 224px contents column on wide screens. The shared contents component highlights the last heading above the reading position. Links and disclosure controls work without JavaScript.
- General controls have at least 44px height, visible keyboard focus and consistent corners. Article links wrap; wide article tables scroll locally. Print excludes navigation and the contents rail.
- Preserve all research-edition labels, source attribution, data, filters, calculators and publication gates.

## Validation

Build with the production base path (`BASE_PATH=/ccu-intelligence/`) so asset routing matches GitHub Pages. Run the existing desktop/mobile browser suite plus coverage for loaded styles, collection links, reading-position navigation, print behavior, and 360px/768px layout overflow. Screenshots are captured by the browser suite for homepage, issue and project filters.
