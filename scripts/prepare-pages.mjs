import { readFile, readdir, rename, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const root = join(process.cwd(), 'dist', 'client');
const source = join(root, '_next');
const target = join(root, 'assets');

async function rewrite(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) await rewrite(path);
    else if (/\.(?:html|js|json|rsc|txt|css)$/.test(entry.name)) {
      const original = await readFile(path, 'utf8');
      const updated = original.replaceAll('/_next/', '/assets/');
      if (updated !== original) await writeFile(path, updated);
    }
  }
}

await rewrite(root);
await rm(target, { recursive: true, force: true });
await rename(source, target);
