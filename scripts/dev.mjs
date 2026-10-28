#!/usr/bin/env node
// Start the whole CyberStratum development stack with one command.
//
//   npm run dev        start everything (and keep it running)
//   npm run stop       stop everything again
//   npm run logs       tail the development log
//
// "npm run dev" starts, in order:
//   1. PostgreSQL   (the isolated cluster on port 5433)
//   2. Redis        (port 6379)
//   3. the API      (FastAPI on port 8000)
//   4. the RQ worker
//   5. the web UI   (Next.js on port 3100)
//
// Services that are already running are left alone, so the command is safe
// to re-run.
//
// How it is put together
// ----------------------
// A detached supervisor process owns the API, the worker and the web UI, and
// writes what they log to .dev-logs/dev.log. The command you type only tails
// that log. This matters because npm sits between the terminal and the
// script: npm tears its own process tree down on Ctrl+C, which would
// otherwise take the application with it and leave PostgreSQL and Redis
// running. "npm run stop" cleans up whatever is left.
//
// Options:
//   --no-infra      do not start PostgreSQL or Redis
//   --no-migrate    do not run "alembic upgrade head" before the API starts
//   --prod          serve the web UI from the existing production build
//                   (npm run build:web) instead of running "next dev"
//   --api-port N    port for the API          (default 8000)
//   --web-port N    port for the web UI       (default 3100)
//
// Every path can be overridden with an environment variable, so the script
// is not welded to this machine:
//   PG_BIN, PG_DATA, PG_LOG, REDIS_BIN

import { spawn, spawnSync } from "node:child_process";
import {
  closeSync, existsSync, mkdirSync, openSync, readFileSync, rmSync,
  writeFileSync, writeSync,
} from "node:fs";
import net from "node:net";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const thisFile = fileURLToPath(import.meta.url);
const root = path.resolve(path.dirname(thisFile), "..");

const PG_BIN = process.env.PG_BIN ?? "E:/tools/pg17/pgsql/bin";
const PG_DATA = process.env.PG_DATA ?? "E:/data/cyberstratum/pgdata";
const PG_LOG = process.env.PG_LOG ?? "E:/data/cyberstratum/pg17.log";
const REDIS_BIN =
  process.env.REDIS_BIN ?? "E:/tools/redis8/Redis-8.10.3-Windows-x64-msys2";

const API_PORT = Number(argValue("--api-port") ?? 8000);
const WEB_PORT = Number(argValue("--web-port") ?? 3100);
const START_INFRA = !process.argv.includes("--no-infra");
const RUN_MIGRATIONS = !process.argv.includes("--no-migrate");
const WEB_MODE = process.argv.includes("--prod") ? "start" : "dev";
const STOP_ONLY = process.argv.includes("--stop");
const LOGS_ONLY = process.argv.includes("--logs");
const SUPERVISOR = process.argv.includes("--supervise");

const PG_PORT = 5433;
const REDIS_PORT = 6379;

const logDir = path.join(root, ".dev-logs");
const logFile = path.join(logDir, "dev.log");
const stateFile = path.join(root, ".dev-session.json");

const COLOURS = {
  reset: "\x1b[0m", bold: "\x1b[1m", dim: "\x1b[2m",
  red: "\x1b[31m", green: "\x1b[32m", yellow: "\x1b[33m",
  blue: "\x1b[34m", magenta: "\x1b[35m", cyan: "\x1b[36m",
};

function argValue(flag) {
  const index = process.argv.indexOf(flag);
  return index === -1 ? undefined : process.argv[index + 1];
}

function log(message) {
  console.log(`${COLOURS.dim}[dev]${COLOURS.reset} ${message}`);
}

function fail(message) {
  console.error(`${COLOURS.red}[dev]${COLOURS.reset} ${message}`);
}

function tool(name) {
  return path.join(PG_BIN, `${name}.exe`);
}

function redisTool(name) {
  return path.join(REDIS_BIN, `${name}.exe`);
}

function nextBin() {
  const candidates = [
    path.join(root, "apps", "web", "node_modules", "next", "dist", "bin", "next"),
    path.join(root, "node_modules", "next", "dist", "bin", "next"),
  ];
  const found = candidates.find((candidate) => existsSync(candidate));
  if (!found) {
    fail("could not find the Next.js CLI - run `npm install` first.");
    process.exit(1);
  }
  return found;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function isListening(port, host = "127.0.0.1") {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host });
    const finish = (result) => {
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(1200);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

async function waitForPort(port, label, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isListening(port)) return true;
    await sleep(400);
  }
  fail(`${label} did not start listening on port ${port}`);
  return false;
}

async function waitForHttp(url, label, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2500) });
      if (response.ok) return true;
    } catch {
      // not up yet
    }
    await sleep(500);
  }
  fail(`${label} did not answer on ${url}`);
  return false;
}

/**
 * Whether a worker is registered on the RQ queue.
 *
 * The worker has no port of its own, so a worker that failed to start is
 * invisible to the port checks. A stack with no worker accepts scans that
 * are then never processed, so this is checked explicitly.
 */
function workerIsRegistered() {
  const cli = redisTool("redis-cli");
  if (!existsSync(cli)) return true; // cannot check, so do not block the start
  const result = spawnSync(cli, ["-h", "127.0.0.1", "-p", String(REDIS_PORT),
    "--scan", "--pattern", "rq:worker:*"], { encoding: "utf8", shell: false });
  if (result.status !== 0) return true;
  return (result.stdout ?? "").includes("cyberstratum-worker");
}

async function waitForWorker(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    // A worker child that has already died will never register.
    if (loadState().workerFailed) return false;
    if (workerIsRegistered()) {
      // Re-check, in case it died in the same moment it registered.
      return !loadState().workerFailed;
    }
    await sleep(500);
  }
  return false;
}

/* ------------------------------------------------------------------ state */

function saveState(state) {
  writeFileSync(stateFile, `${JSON.stringify(state, null, 2)}\n`);
}

function loadState() {
  try {
    return JSON.parse(readFileSync(stateFile, "utf8"));
  } catch {
    return {};
  }
}

/** Report whether a process is alive, without the risk os.kill carries. */
function isAlive(pid) {
  if (!pid) return false;
  const result = spawnSync("tasklist", ["/FI", `PID eq ${pid}`, "/NH"],
    { encoding: "utf8", shell: false });
  if (result.status !== 0) return false;
  return (result.stdout ?? "").includes(String(pid));
}

/* ------------------------------------------------------------------- logs */

function appendToLog(text) {
  try {
    mkdirSync(logDir, { recursive: true });
    const handle = openSync(logFile, "a");
    writeSync(handle, text);
    closeSync(handle);
  } catch {
    // logging must never break the stack
  }
}

/* -------------------------------------------------------------- supervisor */

const children = [];
let shuttingDown = false;

/** Spawn a long-running child whose output goes to the shared log file. */
function supervise(name, command, args, options = {}) {
  const colour = options.colour ?? COLOURS.cyan;
  const child = spawn(command, args, {
    cwd: options.cwd ?? root,
    env: { ...process.env, ...options.env },
    stdio: ["ignore", "pipe", "pipe"],
    shell: false,
  });
  children.push(child);

  const state = loadState();
  state.pids ??= {};
  state.pids[name] = child.pid;
  saveState(state);

  const prefix = `${colour}[${name}]${COLOURS.reset} `;
  const pipe = (stream) => {
    let buffer = "";
    stream.on("data", (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const text = `${prefix}${line}\n`;
        appendToLog(text);
        if (!SUPERVISOR) process.stdout.write(text);
      }
    });
  };
  pipe(child.stdout);
  pipe(child.stderr);

  child.on("exit", (code, signal) => {
    if (shuttingDown) return;
    const text = `${COLOURS.red}[dev]${COLOURS.reset} ${name} exited unexpectedly ` +
      `(code ${code}, signal ${signal ?? "none"})\n`;
    appendToLog(text);
    if (!SUPERVISOR) process.stderr.write(text);
    if (name === "worker") {
      // Record it, so the launcher can tell the user instead of reporting
      // a stack that will never process a scan.
      const state = loadState();
      state.workerFailed = true;
      saveState(state);
      // The usual cause is a worker of the same name that is still alive.
      const hint = `${COLOURS.yellow}[dev]${COLOURS.reset} the worker could not ` +
        `register: a worker named 'cyberstratum-worker' is most likely still ` +
        `running. Run "npm run stop" and then "npm run dev" again.\n`;
      appendToLog(hint);
      if (!SUPERVISOR) process.stderr.write(hint);
    }
  });
  return child;
}

function run(command, args, options = {}) {
  return spawnSync(command, args, {
    cwd: options.cwd ?? root,
    env: { ...process.env, ...options.env },
    stdio: options.quiet ? "ignore" : "inherit",
    shell: false,
  });
}

async function startPostgres() {
  if (await isListening(PG_PORT)) {
    log(`PostgreSQL already listening on ${PG_PORT}`);
    return;
  }
  if (!existsSync(PG_DATA)) {
    fail(`PostgreSQL data directory not found: ${PG_DATA}`);
    fail("Set PG_DATA, or create the cluster with initdb first.");
    process.exitCode = 1;
    return;
  }
  if (!existsSync(tool("pg_ctl"))) {
    fail(`pg_ctl not found in ${PG_BIN}. Set PG_BIN.`);
    process.exitCode = 1;
    return;
  }

  // A cluster that was killed hard leaves its pid file behind, and
  // PostgreSQL refuses to start while that file is present.
  const pidFile = path.join(PG_DATA, "postmaster.pid");
  if (existsSync(pidFile)) {
    rmSync(pidFile, { force: true });
    log("removed a stale postmaster.pid");
  }

  log("starting PostgreSQL...");
  const state = loadState();
  state.postgres = { dataDir: PG_DATA, started: true };
  saveState(state);
  const result = run(tool("pg_ctl"), ["-D", PG_DATA, "-l", PG_LOG, "-w", "start"],
    { quiet: true });
  if (result.status !== 0) {
    fail(`pg_ctl start failed - see ${PG_LOG}`);
    process.exitCode = 1;
    return;
  }
  await waitForPort(PG_PORT, "PostgreSQL");
  log(`PostgreSQL ready on 127.0.0.1:${PG_PORT}`);
}

async function startRedis() {
  if (await isListening(REDIS_PORT)) {
    log(`Redis already listening on ${REDIS_PORT}`);
    return;
  }
  const server = redisTool("redis-server");
  if (!existsSync(server)) {
    fail(`redis-server not found in ${REDIS_BIN}. Set REDIS_BIN.`);
    process.exitCode = 1;
    return;
  }
  log("starting Redis...");
  const state = loadState();
  state.redis = { port: REDIS_PORT, started: true };
  saveState(state);
  supervise("redis", server, ["--port", String(REDIS_PORT), "--bind", "127.0.0.1",
    "--save", "", "--appendonly", "no"], { colour: COLOURS.yellow });
  await waitForPort(REDIS_PORT, "Redis");
  log(`Redis ready on 127.0.0.1:${REDIS_PORT}`);
}

async function supervisorMain() {
  mkdirSync(logDir, { recursive: true });
  const state = loadState();
  state.supervisor = { pid: process.pid, startedAt: new Date().toISOString() };
  state.workerFailed = false;
  saveState(state);

  appendToLog(`\n=== CyberStratum starting at ${new Date().toISOString()} ===\n`);

  if (START_INFRA) {
    await startPostgres();
    await startRedis();
  } else {
    log("skipping PostgreSQL and Redis (--no-infra)");
  }

  if (RUN_MIGRATIONS) {
    log("running database migrations...");
    const result = run("node", [path.join(root, "scripts", "py.mjs"), "-m", "alembic",
      "upgrade", "head"], { quiet: true });
    if (result.status !== 0) {
      fail("alembic upgrade head failed");
      process.exitCode = 1;
      return;
    }
    log("migrations are up to date");
  }

  const webEnv = path.join(root, "apps", "web", ".env.local");
  if (!existsSync(webEnv)) {
    log(`${COLOURS.yellow}warning${COLOURS.reset}: apps/web/.env.local is missing -`);
    log("         the web UI will not be able to reach the API.");
  }

  log("starting the API...");
  supervise("api", "node", [path.join(root, "scripts", "py.mjs"), "-m", "uvicorn",
    "app.main:app", "--app-dir", "apps/api", "--host", "127.0.0.1",
    "--port", String(API_PORT)], { colour: COLOURS.blue });

  log("starting the worker...");
  supervise("worker", "node", [path.join(root, "scripts", "py.mjs"), "--cwd", "apps/api",
    "-m", "app.worker"], { colour: COLOURS.green });

  log("starting the web UI...");
  supervise("web", process.execPath, [nextBin(), WEB_MODE, "-p", String(WEB_PORT)],
    { cwd: path.join(root, "apps", "web"), colour: COLOURS.magenta });

  await waitForHttp(`http://127.0.0.1:${API_PORT}/api/health`, "The API");
  await waitForHttp(`http://127.0.0.1:${WEB_PORT}/`, "The web UI");

  // The worker has no port, so it is checked explicitly. A stack without a
  // worker accepts scans that are then never processed, and saying "up"
  // would be a lie.
  const workerReady = await waitForWorker(20_000);
  if (!workerReady) {
    fail("the RQ worker did not register on the queue.");
    fail("The stack will not process scans. Check .dev-logs/dev.log.");
    return;
  }

  // The launcher prints the banner, so the log line adds what the banner
  // cannot show: that the worker is registered and will pick up scans.
  appendToLog("\nthe RQ worker is registered on cyberstratum:scans.\n");
  log("the stack is up");
}

/* ------------------------------------------------------------------- stop */

function pidsOnPort(port) {
  const result = spawnSync("netstat", ["-ano"], { encoding: "utf8", shell: false });
  if (result.status !== 0) return [];
  const pids = new Set();
  for (const line of (result.stdout ?? "").split(/\r?\n/)) {
    if (!line.includes("LISTENING")) continue;
    if (!new RegExp(`[:.]${port}\\s`).test(line)) continue;
    const pid = line.trim().split(/\s+/).pop();
    if (pid && pid !== "0") pids.add(pid);
  }
  return [...pids];
}

function killPid(pid, label) {
  if (!pid) return;
  const result = spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"],
    { encoding: "utf8", shell: false });
  if (result.status === 0) log(`${label}: stopped pid ${pid}`);
}

function killPort(port, label) {
  for (const pid of pidsOnPort(port)) killPid(pid, label);
}

/** Every process id, its parent, and its command line. */
function processList() {
  const script =
    "Get-CimInstance Win32_Process | " +
    "ForEach-Object { \"$($_.ProcessId)`t$($_.ParentProcessId)`t$($_.CommandLine)\" }";
  const result = spawnSync("powershell", ["-NoProfile", "-Command", script],
    { encoding: "utf8", shell: false, maxBuffer: 32 * 1024 * 1024 });
  if (result.status !== 0) return [];
  const processes = [];
  for (const line of (result.stdout ?? "").split(/\r?\n/)) {
    const parts = line.split("\t");
    if (parts.length < 2) continue;
    const pid = Number(parts[0].trim());
    const parent = Number(parts[1].trim());
    if (!pid) continue;
    processes.push({ pid, parent, command: parts[2] ?? "" });
  }
  return processes;
}

/** The pids of this process and everything that leads to it. */
function ancestorPids(processes) {
  const byPid = new Map(processes.map((entry) => [entry.pid, entry]));
  const ancestors = new Set();
  let current = process.pid;
  while (current && !ancestors.has(current)) {
    ancestors.add(current);
    current = byPid.get(current)?.parent;
  }
  return ancestors;
}

/**
 * Kill leftover processes that belong to this project.
 *
 * The API and the web UI are found by their ports, but the RQ worker has no
 * port of its own, and a worker left behind by an earlier run would keep a
 * stale registration in Redis. The command line is the only reliable
 * marker for those, so it is used as well.
 */
function sweepProjectProcesses() {
  const processes = processList();
  const skip = ancestorPids(processes);
  const patterns = [
    { name: "worker", pattern: /app\.worker/ },
    { name: "API", pattern: /app\.main:app/ },
    { name: "dev script", pattern: /scripts[\\/]dev\.mjs/ },
  ];
  for (const { name, pattern } of patterns) {
    for (const entry of processes) {
      if (skip.has(entry.pid)) continue;
      if (!pattern.test(entry.command)) continue;
      killPid(entry.pid, name);
    }
  }
}

function stopRedis() {
  const cli = redisTool("redis-cli");
  if (!existsSync(cli)) return;
  const result = spawnSync(cli, ["-h", "127.0.0.1", "-p", String(REDIS_PORT),
    "shutdown", "nosave"], { encoding: "utf8", shell: false });
  if (result.status === 0) log("Redis: stopped");
}

function stopPostgres() {
  if (!existsSync(tool("pg_ctl"))) return;
  const result = spawnSync(tool("pg_ctl"), ["-D", PG_DATA, "-m", "fast", "-w", "stop"],
    { encoding: "utf8", shell: false });
  if (result.status === 0) log("PostgreSQL: stopped");
}

async function stopEverything() {
  console.log(`${COLOURS.dim}[dev]${COLOURS.reset} stopping the development stack...`);

  const state = loadState();

  // The supervisor owns the API, the worker and the web UI, so killing its
  // tree takes them with it.
  if (state.supervisor?.pid) killPid(state.supervisor.pid, "supervisor");
  for (const [name, pid] of Object.entries(state.pids ?? {})) {
    if (name === "supervisor") continue;
    killPid(pid, name);
  }

  // A port may still be held by a process the tree kill missed.
  killPort(WEB_PORT, "web UI");
  killPort(API_PORT, "API");
  sweepProjectProcesses();
  stopRedis();
  stopPostgres();

  const pidFile = path.join(PG_DATA, "postmaster.pid");
  if (existsSync(pidFile) && !(await isListening(PG_PORT))) {
    rmSync(pidFile, { force: true });
  }
  rmSync(stateFile, { force: true });
  console.log(`${COLOURS.green}[dev]${COLOURS.reset} everything is stopped.`);
}

/* ----------------------------------------------------------------- front */

async function tailLog() {
  let position = 0;
  for (;;) {
    if (existsSync(logFile)) {
      const content = readFileSync(logFile, "utf8");
      if (content.length > position) {
        process.stdout.write(content.slice(position));
        position = content.length;
      }
    }
    await sleep(400);
  }
}

function startSupervisor() {
  const state = loadState();
  if (state.supervisor?.pid && isAlive(state.supervisor.pid)) {
    log(`the stack is already running (supervisor pid ${state.supervisor.pid})`);
    return true;
  }
  mkdirSync(logDir, { recursive: true });
  rmSync(logFile, { force: true });
  const child = spawn(process.execPath, [thisFile, "--supervise"], {
    cwd: root,
    detached: true,
    stdio: "ignore",
  });
  child.unref();
  log(`starting the development stack (supervisor pid ${child.pid})`);
  return false;
}

function requestStop() {
  // The cleanup is handed to a detached process. npm tears its own process
  // tree down on Ctrl+C, which would otherwise interrupt the cleanup and
  // leave PostgreSQL and Redis running.
  const helper = spawn(process.execPath, [thisFile, "--stop"],
    { detached: true, stdio: "ignore" });
  helper.unref();
}

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log(`\n${COLOURS.dim}[dev] shutting down...${COLOURS.reset}`);
  requestStop();
  setTimeout(() => process.exit(0), 400);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

async function main() {
  if (STOP_ONLY) {
    await stopEverything();
    return;
  }
  if (LOGS_ONLY) {
    await tailLog();
    return;
  }
  if (SUPERVISOR) {
    await supervisorMain();
    return;
  }

  console.log(`${COLOURS.blue}CyberStratum${COLOURS.reset} - starting the development stack`);
  const alreadyRunning = startSupervisor();

  // Give the supervisor a moment to write its first lines.
  await sleep(1200);
  tailLog().catch(() => {
    // the log file may disappear while it is being read
  });

  const ready = await waitForHttp(`http://127.0.0.1:${API_PORT}/api/health`,
    "The API", 120_000);
  const webReady = await waitForHttp(`http://127.0.0.1:${WEB_PORT}/`, "The web UI", 120_000);
  const workerReady = await waitForWorker(30_000);

  if (!workerReady) {
    fail("the RQ worker did not register on the queue.");
    fail("A worker named 'cyberstratum-worker' is most likely still running.");
    fail("Run \"npm run stop\" and then \"npm run dev\" again.");
  }

  if (ready && webReady && workerReady) {
    console.log(`
${COLOURS.green}${COLOURS.bold}CyberStratum is up.${COLOURS.reset}
  web UI      http://127.0.0.1:${WEB_PORT}
  API         http://127.0.0.1:${API_PORT}
  API docs    http://127.0.0.1:${API_PORT}/docs
  health      http://127.0.0.1:${API_PORT}/api/health
  PostgreSQL  127.0.0.1:${PG_PORT}     Redis  127.0.0.1:${REDIS_PORT}

  Press Ctrl+C to stop, or run "npm run stop" from another terminal.
  Logs are in .dev-logs/dev.log ("npm run logs" tails them).
`);
  } else if (!alreadyRunning) {
    fail("the stack did not come up - check .dev-logs/dev.log");
  }

}

main().catch((error) => {
  fail(String(error?.stack ?? error));
  shutdown();
});
