import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

// Writes one notice file for every production npm package the web image ships, with the
// license text each package carries. Usage: node scripts/collect-licenses.mjs <output>.
const output = process.argv[2];
if (!output) {
  console.error("usage: node scripts/collect-licenses.mjs <output>");
  process.exit(2);
}

const NOTICE = /^(licen[cs]e|copying|notice)(\.|-|$)/i;
const COPYLEFT = /\b(A?GPL|LGPL|MPL|EPL|CDDL|SSPL)\b/i;

const report = JSON.parse(
  execFileSync("pnpm", ["licenses", "list", "--prod", "--json"], {
    cwd: path.join(import.meta.dirname, ".."),
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  }),
);

const packages = Object.values(report)
  .flat()
  .sort((a, b) => a.name.localeCompare(b.name));

const flagged = packages.filter((pkg) => COPYLEFT.test(pkg.license));
if (flagged.length > 0) {
  console.error(`copyleft licenses need review: ${flagged.map((p) => p.name).join(", ")}`);
  process.exit(1);
}

const sections = packages.map((pkg) => {
  const texts = [];
  for (const dir of pkg.paths) {
    for (const name of readdirSync(dir)
      .filter((n) => NOTICE.test(n))
      .sort()) {
      texts.push(readFileSync(path.join(dir, name), "utf8").trim());
    }
  }
  const body = texts.length > 0 ? [...new Set(texts)].join("\n\n") : `License: ${pkg.license}`;
  return `${pkg.name} ${pkg.versions.join(", ")} (${pkg.license})\n\n${body}`;
});

writeFileSync(
  output,
  `Third-party npm packages in the Costura web image\n\n${sections.join(`\n\n${"-".repeat(72)}\n\n`)}\n`,
);
console.log(`${packages.length} packages written to ${output}`);
