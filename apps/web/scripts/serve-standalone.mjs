import { existsSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

const { values } = parseArgs({
  options: {
    hostname: { type: "string", default: "0.0.0.0" },
    port: { type: "string", default: "3000" },
  },
});
const root = path.join(import.meta.dirname, "..");
const standalone = path.join(root, ".next", "standalone");
const server = path.join(standalone, "server.js");
if (!existsSync(path.join(standalone, ".next", "static"))) {
  console.error(
    `${path.relative(root, standalone)} has no static assets; run \`pnpm build\` first`,
  );
  process.exit(1);
}
process.env.HOSTNAME = values.hostname;
process.env.PORT = values.port;
process.chdir(standalone);
await import(pathToFileURL(server).href);
