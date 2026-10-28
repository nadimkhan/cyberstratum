#!/usr/bin/env node
// Run a Python module from the project virtual environment.
//
// The npm scripts must work whether or not the venv is activated, and on
// Windows and POSIX alike. This resolves the interpreter once -- preferring
// the in-repo .venv, falling back to whatever Python is on PATH -- and then
// hands the remaining arguments to it.
//
//   node scripts/py.mjs -m pytest -q
//   node scripts/py.mjs -m ruff check apps packages tests scripts

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const candidates = [
  path.join(root, ".venv", "Scripts", "python.exe"),
  path.join(root, ".venv", "bin", "python"),
  path.join(root, ".venv", "bin", "python3"),
];

const venv = candidates.find((candidate) => existsSync(candidate));
const interpreter = venv ?? (process.platform === "win32" ? "python" : "python3");

if (!venv) {
  console.error(
    "[cybersratum] No .venv found at the repository root. Create it with:\n" +
      "  uv venv .venv && uv pip install --python .venv/Scripts/python.exe -e packages/evm_analysis -e packages/ml_baseline -e .",
  );
}

const result = spawnSync(interpreter, process.argv.slice(2), {
  cwd: root,
  stdio: "inherit",
});

if (result.error) {
  console.error(`[cyberstratum] Failed to run ${interpreter}: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
