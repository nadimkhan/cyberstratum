import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { SEVERITY_PALETTE } from "./severity";
import { SEVERITY_ORDER } from "./types";

const ROOT = fileURLToPath(new URL("../..", import.meta.url));

function relativeLuminance(hex: string): number {
  const channels = [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16) / 255);
  const linear = channels.map((value) =>
    value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/** WCAG 2.x contrast ratio between two hex colours. */
function contrastRatio(a: string, b: string): number {
  const first = relativeLuminance(a);
  const second = relativeLuminance(b);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

function walk(dir: string): string[] {
  const entries: string[] = [];
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) entries.push(...walk(full));
    else if (/\.(ts|tsx|css)$/.test(entry)) entries.push(full);
  }
  return entries;
}

describe("severity palette accessibility", () => {
  it("meets WCAG AA (4.5:1) for badge text in the light palette", () => {
    for (const severity of SEVERITY_ORDER) {
      const palette = SEVERITY_PALETTE[severity];
      const ratio = contrastRatio(palette.lightFg, palette.lightBg);
      expect(ratio, `${severity} light contrast is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("meets WCAG AA (4.5:1) for badge text in the dark palette", () => {
    for (const severity of SEVERITY_ORDER) {
      const palette = SEVERITY_PALETTE[severity];
      const ratio = contrastRatio(palette.darkFg, palette.darkBg);
      expect(ratio, `${severity} dark contrast is ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("severity colour is defined in exactly one place", () => {
  const severityFile = join(ROOT, "src", "lib", "severity.ts");
  // The five hue families owned by the severity taxonomy. Other components
  // (scan status, review status) must use different families so a severity
  // colour can never be redefined outside this file.
  const severityPatterns = [
    /text-(red|orange|yellow|sky|cyan)-(700|800|900)/,
    /bg-(red|orange|yellow|sky|cyan)-(100|200)/,
    /dark:bg-(red|orange|yellow|sky|cyan)-500/,
    /dark:text-(red|orange|yellow|sky|cyan)-(100|200|300)/,
  ];

  it("does not define severity colours outside src/lib/severity.ts", () => {
    const offenders: string[] = [];
    for (const file of walk(join(ROOT, "src")).concat(walk(join(ROOT, "app")))) {
      if (file === severityFile) continue;
      const source = readFileSync(file, "utf8");
      if (severityPatterns.some((pattern) => pattern.test(source))) {
        offenders.push(relative(ROOT, file).split(sep).join("/"));
      }
    }
    expect(offenders).toEqual([]);
  });
});
