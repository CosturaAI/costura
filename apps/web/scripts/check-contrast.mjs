import { readFileSync } from "node:fs";
import path from "node:path";

function hex(value) {
  const match = value.trim().match(/^#([0-9a-f]{6})$/i);
  if (!match) throw new Error(`not a hex color: ${value}`);
  const n = Number.parseInt(match[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function luminance(rgb) {
  const channel = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const [r, g, b] = rgb.map(channel);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const lighter = Math.max(luminance(hex(a)), luminance(hex(b)));
  const darker = Math.min(luminance(hex(a)), luminance(hex(b)));
  return (lighter + 0.05) / (darker + 0.05);
}

function vars(file) {
  const text = readFileSync(file, "utf8");
  const found = {};
  for (const match of text.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    found[match[1]] = match[2].toLowerCase();
  }
  return found;
}

const dir = path.join(import.meta.dirname, "..", "src", "themes");
const pairs = [
  ["foreground", "background"],
  ["muted-foreground", "background"],
  ["muted-foreground", "muted"],
  ["faint-foreground", "background"],
  ["primary-foreground", "primary"],
  ["critical", "critical-bg"],
  ["warning", "warning-bg"],
  ["info", "info-bg"],
  ["success", "success-bg"],
  ["foreground", "card"],
];

let failed = false;
for (const file of ["costura.css", "costura-dark.css"]) {
  const values = vars(path.join(dir, file));
  for (const [fg, bg] of pairs) {
    const score = ratio(values[fg], values[bg]);
    const ok = score >= 4.5;
    if (!ok) failed = true;
    console.log(`${file} ${fg} on ${bg}: ${score.toFixed(2)} ${ok ? "AA" : "FAIL"}`);
  }
}
if (failed) process.exit(1);
