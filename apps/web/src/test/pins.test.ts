/**
 * Every entry of `dependencies` and `devDependencies` in `package.json` is an exact version,
 * so the lockfile and the release image carry the packages CI tested. `engines` and
 * `packageManager` are ranges or tool pins by design and are not checked here.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const EXACT_VERSION = /^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/;

type PackageJson = {
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
};

const manifest = JSON.parse(
  readFileSync(resolve(__dirname, "../../package.json"), "utf8"),
) as PackageJson;

describe("package.json pins", () => {
  it.each(["dependencies", "devDependencies"] as const)("%s use exact versions", (field) => {
    const entries = Object.entries(manifest[field] ?? {});
    expect(entries.length).toBeGreaterThan(0);
    const ranged = entries.filter(([, version]) => !EXACT_VERSION.test(version));
    expect(ranged).toEqual([]);
  });
});
