import { build } from "esbuild";
import { mkdir, copyFile, cp } from "node:fs/promises";
await mkdir("dist", { recursive: true });
await build({
  entryPoints: ["src/app.mjs"],
  bundle: true,
  format: "esm",
  outfile: "dist/app.js",
  target: ["es2022"],
  sourcemap: true,
  minify: true,
  legalComments: "linked",
});
await copyFile("index.html", "dist/index.html");
await copyFile(
  "node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs",
  "dist/maplibre-worker.js",
);
await cp("public", "dist", { recursive: true });
