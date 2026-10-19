import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const root = path.join(import.meta.dirname, "..", "src");
const pattern = /(?:text|bg|border|ring)-(?:gray|brand|surface|red|amber|emerald|blue|orange)-\d+/;
const allow = [`${path.sep}components${path.sep}ui${path.sep}`, `${path.sep}themes${path.sep}`];

function walk(dir, hits) {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      walk(full, hits);
      continue;
    }
    if (!name.endsWith(".tsx") && !name.endsWith(".ts") && !name.endsWith(".css")) continue;
    if (allow.some((part) => full.includes(part))) continue;
    const lines = readFileSync(full, "utf8").split("\n");
    lines.forEach((line, index) => {
      if (pattern.test(line))
        hits.push(`${path.relative(root, full)}:${index + 1}: ${line.trim()}`);
    });
  }
}

const hits = [];
walk(root, hits);
if (hits.length > 0) {
  console.error("Raw palette classes are only allowed in src/themes and src/components/ui:");
  hits.forEach((hit) => console.error(hit));
  process.exit(1);
}
