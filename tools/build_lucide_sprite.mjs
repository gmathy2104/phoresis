import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { execSync } from "node:child_process";
import { createRequire } from "node:module";

const ICONS = [
  "home", "layout-dashboard", "image", "upload", "download", "file-text", "settings",
  "search", "bell", "user", "log-out", "log-in", "plus", "edit", "trash-2", "copy", "eye",
  "chevron-down", "chevron-up", "chevron-left", "chevron-right", "x", "check",
  "alert-circle", "alert-triangle", "info", "check-circle", "loader", "sun", "moon",
  "monitor", "palette", "flask-conical", "microscope", "beaker", "kanban", "wrench",
  "trending-up", "bar-chart-3", "pie-chart", "command", "sparkles", "more-horizontal",
  "filter", "sort-asc", "layers", "grid-2x2", "list", "refresh-cw",
];

execSync("npm install lucide-static --no-save --silent", { stdio: "inherit" });

const require = createRequire(import.meta.url);

const symbols = ICONS.map((name) => {
  const path = require.resolve(`lucide-static/icons/${name}.svg`);
  let svg = readFileSync(path, "utf-8");
  svg = svg.replace(/<svg[^>]*>/, "").replace(/<\/svg>/, "");
  return `<symbol id="lucide-${name}" viewBox="0 0 24 24" stroke="currentColor" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${svg}</symbol>`;
}).join("");

const sprite = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none">${symbols}</svg>`;

const outPath = resolve("src/phoresis_ui/static/phoresis_ui/icons/lucide.svg");
mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, sprite);
console.log(`Wrote ${outPath} (${ICONS.length} icons)`);
