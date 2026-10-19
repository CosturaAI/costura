import { cpSync, existsSync, rmSync } from "node:fs";
import path from "node:path";

const root = path.join(import.meta.dirname, "..");
const standalone = path.join(root, ".next", "standalone");
if (existsSync(standalone)) {
  for (const [from, to] of [
    [path.join(root, ".next", "static"), path.join(standalone, ".next", "static")],
    [path.join(root, "public"), path.join(standalone, "public")],
  ]) {
    rmSync(to, { recursive: true, force: true });
    cpSync(from, to, { recursive: true });
  }
}
