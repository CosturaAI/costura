import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SRC = path.join(process.cwd(), "src");
const read = (relative: string) => readFileSync(path.join(SRC, relative), "utf8");

function tokens(block: string): string[] {
  return [...block.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1]!).sort();
}

function blockAfter(css: string, selector: string): string {
  const start = css.indexOf(selector);
  expect(start, `${selector} is declared`).toBeGreaterThanOrEqual(0);
  const open = css.indexOf("{", start);
  return css.slice(open + 1, css.indexOf("}", open));
}

describe("theme stylesheets", () => {
  it("binds the dark: variant to data-theme, not to the OS alone", () => {
    const globals = read("app/globals.css");
    expect(globals).toMatch(/@custom-variant dark \{/);
    expect(globals).toContain('&:where([data-theme="dark"], [data-theme="dark"] *)');
    expect(globals).toMatch(
      /@media \(prefers-color-scheme: dark\) \{\s*&:where\(\[data-theme="system"\]/,
    );
  });

  it("gives the dark and system schemes the same color tokens as light", () => {
    const shape = new Set(["--radius"]);
    const light = tokens(blockAfter(read("themes/costura.css"), ":root")).filter(
      (token) => !shape.has(token),
    );
    const dark = read("themes/costura-dark.css");
    const explicit = tokens(blockAfter(dark, 'html[data-theme="dark"]'));
    const system = tokens(blockAfter(dark, 'html[data-theme="system"]'));
    expect(explicit).toEqual(system);
    expect(light.filter((token) => !explicit.includes(token))).toEqual([]);
  });

  it("keeps raw colors out of the shared ui primitives", () => {
    const dir = path.join(SRC, "components/ui");
    // Recharts draws its defaults with these literals; the primitives only match them.
    const rechartsDefaults = /\[stroke='#(?:ccc|fff)'\]/g;
    for (const file of readdirSync(dir)) {
      const source = readFileSync(path.join(dir, file), "utf8").replace(rechartsDefaults, "");
      expect(source, file).not.toMatch(/#[0-9a-f]{3,8}\b|\b(?:rgb|rgba|hsl|oklch)\(/i);
    }
  });
});
