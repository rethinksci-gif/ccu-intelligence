import fs from 'node:fs';
import path from 'node:path';
const root = path.resolve('dist');
const base = (process.env.BASE_PATH || '/').replace(/\/$/, '');
const files = fs.readdirSync(root, { recursive: true }).filter((f) => f.endsWith('.html'));
const errors = [];
for (const file of files) {
  const html = fs.readFileSync(path.join(root, file), 'utf8');
  for (const match of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    const raw = match[1];
    if (/^(https?:|mailto:|data:|tel:|#)/.test(raw)) continue;
    const target = decodeURIComponent(raw.split(/[?#]/)[0]);
    let resolved;
    if (target.startsWith('/')) {
      if (base && !target.startsWith(base + '/')) {
        errors.push(`${file}: wrong base ${raw}`);
        continue;
      }
      resolved = path.join(root, target.slice(base.length));
    } else resolved = path.resolve(path.dirname(path.join(root, file)), target);
    if (!resolved.startsWith(root + path.sep) && resolved !== root) {
      errors.push(`${file}: escapes output ${raw}`);
      continue;
    }
    if (!fs.existsSync(resolved) && !fs.existsSync(path.join(resolved, 'index.html')))
      errors.push(`${file}: missing ${raw}`);
  }
}
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
console.log(`Internal links and assets checked across ${files.length} pages (base: ${base || '/'}).`);
