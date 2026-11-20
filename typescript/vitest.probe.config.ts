import { defineConfig } from "vitest/config";

export default defineConfig({
  root: "..",
  server: { fs: { allow: [".."] } },
  test: { include: ["scripts/probes/**/*.probe.ts"], fileParallelism: false, testTimeout: 60_000 },
});
