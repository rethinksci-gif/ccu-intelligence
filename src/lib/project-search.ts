/** Normalize display spelling only; never alter stored scientific values or units. */
export function searchText(value: string) {
  return value.normalize('NFKD').replace(/\p{M}/gu, '').replace(/ø/gi, 'o').toLowerCase();
}
