import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = path.resolve(__dirname, "..");

const ALLOWED: Record<string, number> = {
  "app/(app)/anomalies/[id]/anomaly-evidence.tsx": 1,
  "app/(app)/anomalies/[id]/page.tsx": 1,
  "app/(app)/anomalies/anomaly-list.tsx": 1,
  "components/alerts-bell.tsx": 1,
  "components/anomalies-card.tsx": 1,
  "components/anomaly-day-table.tsx": 1,
  "components/attribution-table.tsx": 3,
  "components/breakdown-table.tsx": 2,
  "components/budget-bars.tsx": 2,
  "components/charts/daily-spend-chart.tsx": 1,
  "components/inventory-tables.tsx": 1,
  "components/query-chips.tsx": 1,
  "components/sidebar-nav.tsx": 1,
  "components/transposed-spend-table.tsx": 2,
};

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sources(full);
    return full.endsWith(".tsx") && !full.includes(".test.") ? [full] : [];
  });
}

function titleAttributes(file: string): string[] {
  const source = ts.createSourceFile(
    file,
    readFileSync(file, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const hits: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxAttribute(node) && node.name.getText(source) === "title") {
      const tag = node.parent.parent.tagName.getText(source);
      if (/^[a-z]/.test(tag) || tag === "Link") {
        const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
        hits.push(`${path.relative(SRC, file)}:${line + 1} <${tag}>`);
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return hits;
}

describe("title attributes", () => {
  it("carry no information a reader needs, per apps/web/AGENTS.md", () => {
    const counts: Record<string, number> = {};
    for (const hit of sources(SRC).flatMap(titleAttributes)) {
      const file = hit.slice(0, hit.lastIndexOf(":"));
      counts[file] = (counts[file] ?? 0) + 1;
    }
    expect(counts).toEqual(ALLOWED);
  });
});
