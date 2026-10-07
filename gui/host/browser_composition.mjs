// Both entry points use this strict demo selector. The privileged embedding API
// itself always isolates and does not accept a selector.
export function browserComposition(href) {
  const url = new URL(href);
  const query = url.searchParams.getAll('renderer');
  const fragment = new URLSearchParams(url.hash.slice(1)).getAll('renderer');
  const values = [...query,...fragment];
  if (values.length > 1) throw Error('Duplicate renderer selector');
  const value = values[0] ?? 'standalone';
  if (value !== 'standalone' && value !== 'isolated') throw Error('Invalid renderer selector');
  return value;
}
