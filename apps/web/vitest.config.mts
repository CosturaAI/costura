import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    globals: false,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.test.{ts,tsx}",
        "src/test/**",
        "src/components/ui/badge.tsx",
        "src/components/ui/button.tsx",
        "src/components/ui/card.tsx",
        "src/components/ui/checkbox.tsx",
        "src/components/ui/input.tsx",
        "src/components/ui/table.tsx",
        "src/components/ui/tabs.tsx",
      ],
      reporter: ["text-summary", "lcov"],
      thresholds: {
        lines: 92,
        statements: 90,
        branches: 82,
        functions: 88,
        "src/lib/**/*.ts": { perFile: true, lines: 85, branches: 50, functions: 80 },
        "src/actions/**/*.ts": { perFile: true, lines: 95, branches: 65, functions: 100 },
        "src/components/**/*.tsx": { perFile: true, lines: 65, branches: 45, functions: 25 },
      },
    },
  },
});
