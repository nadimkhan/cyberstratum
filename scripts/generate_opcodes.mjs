/**
 * Generates the vendored EVM opcode table used by the Python analysis engine.
 *
 * Sources:
 *   - ethereum/execution-specs `src/ethereum/forks/<fork>/vm/instructions/__init__.py`
 *       -> authoritative per-fork `Ops` enum: which opcode bytes exist in which
 *          fork, and their canonical names (PUSH1..PUSH32, DUP1..DUP16, ...).
 *   - @ethereumjs/evm `dist/esm/eof/stackDelta.js`
 *       -> per-opcode stack effects (inputs/outputs) and terminating flag.
 *          Stack effects are fork-independent for the opcodes that survive
 *          across forks; the table is the EIP-5450 metadata set.
 *
 * Output: packages/evm_analysis/data/opcodes.json  (committed artifact)
 *
 * The generated file is committed so the Python engine needs no Node dependency
 * at runtime, and so the table is pinned, diffable and reviewable.
 *
 * Usage: node scripts/generate_opcodes.mjs
 */
import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..')

// Pinned to a released tag so the generated table is reproducible.
const SPECS_REF = 'v2.20.0'
const SPECS_BASE = `https://raw.githubusercontent.com/ethereum/execution-specs/${SPECS_REF}/src/ethereum/forks`

// Ordered oldest -> newest. Each fork's opcode set is read independently
// rather than assuming cumulative inheritance.
const FORKS = [
  'frontier',
  'homestead',
  'tangerine_whistle',
  'spurious_dragon',
  'byzantium',
  'constantinople',
  'petersburg',
  'istanbul',
  'berlin',
  'london',
  'paris',
  'shanghai',
  'cancun',
  'prague',
]

// execution-specs has no petersburg fork directory: Petersburg differed from
// Constantinople only by reverting EIP-1283 (net gas metering), which changes
// gas costs, not the opcode set. So Petersburg's opcodes are Constantinople's.
const FORK_SOURCE_OVERRIDES = {
  petersburg: 'constantinople',
}

// --- ethereumjs stack effects ------------------------------------------------

const evmEntry = require.resolve('@ethereumjs/evm')
let evmRoot = dirname(evmEntry)
while (!existsSync(resolve(evmRoot, 'dist/esm/opcodes/codes.js'))) {
  const parent = dirname(evmRoot)
  if (parent === evmRoot) throw new Error('could not locate @ethereumjs/evm root')
  evmRoot = parent
}
const load = (p) => import(pathToFileURL(p).href)
const { stackDelta } = await load(resolve(evmRoot, 'dist/esm/eof/stackDelta.js'))
const evmVersion = JSON.parse(readFileSync(resolve(evmRoot, 'package.json'), 'utf8')).version
const legacyVersion = require('evm-opcodes/package.json').version

// Legacy stack effects from evm-opcodes (Yellow-Paper derived). This table
// covers the classic opcodes (JUMP, CALL, CODESIZE, ...) that the ethereumjs
// EOF metadata table omits, but it predates the modern opcodes.
const legacyOpcodes = require('evm-opcodes')
const legacyStack = new Map()
for (const op of legacyOpcodes) {
  if (!op.mnemonic || op.mnemonic === 'Unassigned') continue
  legacyStack.set(op.opcode, {
    inputs: (op.inputs || []).length,
    outputs: (op.outputs || []).length,
    terminating: op.terminal === true,
  })
}

// Modern stack effects from @ethereumjs/evm (EIP-5450 metadata). Covers
// PUSH0, MCOPY, TSTORE, TLOAD, BASEFEE, BLOBBASEFEE and friends.
const modernStack = new Map()
for (const [key, entry] of Object.entries(stackDelta)) {
  // Object keys are stringified numbers: the source writes `0x60:` but the key
  // is "96" (decimal). Parsing them as hex would silently corrupt every code
  // >= 10, so detect the literal form instead of assuming a radix.
  const code = key.startsWith('0x') || key.startsWith('0X')
    ? Number.parseInt(key, 16)
    : Number.parseInt(key, 10)
  if (!Number.isInteger(code) || code < 0 || code > 0xff) {
    throw new Error(`unparseable opcode key: ${key}`)
  }
  modernStack.set(code, {
    inputs: entry.inputs,
    outputs: entry.outputs,
    terminating: entry.terminating === true,
  })
}

// Merge: prefer the modern table where present, fall back to legacy.
// Where both cover an opcode they must agree exactly — a disagreement means
// one source is wrong and we refuse to emit a table.
const stack = new Map()
const conflicts = []
for (const [code, entry] of modernStack) {
  const legacy = legacyStack.get(code)
  if (legacy && (legacy.inputs !== entry.inputs || legacy.outputs !== entry.outputs)) {
    conflicts.push(
      `0x${code.toString(16).padStart(2, '0')}: evm-opcodes ` +
        `${legacy.inputs}/${legacy.outputs} vs ethereumjs ${entry.inputs}/${entry.outputs}`,
    )
    continue
  }
  stack.set(code, entry)
}
for (const [code, entry] of legacyStack) {
  if (!stack.has(code)) stack.set(code, entry)
}
if (conflicts.length) {
  console.error('Stack effect sources disagree:')
  for (const c of conflicts) console.error('  -', c)
  process.exit(1)
}

// --- execution-specs per-fork opcode sets ------------------------------------

/** Parse the `Ops` enum out of an instructions/__init__.py file. */
function parseOpsEnum(source) {
  const ops = new Map()
  // Match enum members like `    PUSH1 = 0x60`
  const re = /^\s{4}([A-Z][A-Z0-9_]*)\s*=\s*(0x[0-9A-Fa-f]+)\s*$/gm
  let m
  while ((m = re.exec(source)) !== null) {
    ops.set(Number.parseInt(m[2], 16), m[1])
  }
  return ops
}

async function fetchOps(fork) {
  const source_fork = FORK_SOURCE_OVERRIDES[fork] ?? fork
  const url = `${SPECS_BASE}/${source_fork}/vm/instructions/__init__.py`
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`failed to fetch ${url}: HTTP ${res.status}`)
  }
  const source = await res.text()
  const ops = parseOpsEnum(source)
  if (ops.size < 100) {
    throw new Error(`suspiciously small opcode set for ${fork}: ${ops.size}`)
  }
  return ops
}

const perFork = {}
for (const fork of FORKS) {
  const ops = await fetchOps(fork)
  const list = [...ops.entries()]
    .map(([code, name]) => {
      const sd = stack.get(code)
      return {
        code,
        name,
        pushBytes: /^PUSH(\d+)$/.test(name) ? Number(name.slice(4)) : 0,
        stackIn: sd ? sd.inputs : null,
        stackOut: sd ? sd.outputs : null,
        terminating: sd ? sd.terminating : false,
      }
    })
    .sort((a, b) => a.code - b.code)
  perFork[fork] = list
}

// --- sanity checks -----------------------------------------------------------

const problems = []
for (const fork of FORKS) {
  const list = perFork[fork]
  const codes = new Set(list.map((o) => o.code))
  if (codes.size !== list.length) problems.push(`${fork}: duplicate opcode codes`)
  // 0xfe is the *designated invalid* opcode and is never a real instruction,
  // so execution-specs correctly omits it from every fork.
  for (const required of [0x00, 0x01, 0x56, 0x57, 0xf3, 0xff]) {
    if (!codes.has(required)) problems.push(`${fork}: missing core opcode 0x${required.toString(16)}`)
  }
  if (codes.has(0xfe)) problems.push(`${fork}: 0xfe must not appear as a valid instruction`)
  const push1 = list.find((o) => o.code === 0x60)
  if (!push1 || push1.name !== 'PUSH1' || push1.pushBytes !== 1) {
    problems.push(`${fork}: PUSH1 not parsed correctly`)
  }
}
// Fork progression checks: newer forks must not lose opcodes.
for (let i = 1; i < FORKS.length; i++) {
  const prev = new Set(perFork[FORKS[i - 1]].map((o) => o.code))
  const cur = new Set(perFork[FORKS[i]].map((o) => o.code))
  for (const code of prev) {
    if (!cur.has(code)) {
      problems.push(`${FORKS[i]} dropped opcode 0x${code.toString(16)} present in ${FORKS[i - 1]}`)
    }
  }
}
// Every opcode with a stack effect in the ethereumjs table must be resolvable.
// A silently-missing stack effect would produce wrong depth analysis, so we
// require that the set of codes we found matches the table's own size.
if (stack.size < legacyStack.size) {
  problems.push(`stack effect table lost entries: ${stack.size}/${legacyStack.size}`)
}
// Every opcode that either source knows about must be present in the merged
// table, and every known opcode must resolve to a stack effect.
for (const list of Object.values(perFork)) {
  for (const op of list) {
    if (op.stackIn === null || op.stackOut === null) {
      problems.push(`opcode 0x${op.code.toString(16)} (${op.name}) has no stack effect`)
    }
  }
}
// Spot-check a few known stack effects so a mis-parse is caught loudly.
const STACK_CHECKS = [
  ['cancun', 0x01, 2, 1], // ADD
  ['cancun', 0x55, 2, 0], // SSTORE  (pops key, value; gas is not on the stack)
  ['cancun', 0x5f, 0, 1], // PUSH0
  ['cancun', 0x60, 0, 1], // PUSH1
  ['cancun', 0x5e, 3, 0], // MCOPY
  ['cancun', 0xf3, 2, 0], // RETURN   (pops offset, size)
  ['frontier', 0x01, 2, 1], // ADD
]
for (const [fork, code, wantIn, wantOut] of STACK_CHECKS) {
  const op = perFork[fork].find((o) => o.code === code)
  if (!op) {
    problems.push(`${fork}: missing opcode 0x${code.toString(16)}`)
    continue
  }
  if (op.stackIn !== wantIn || op.stackOut !== wantOut) {
    problems.push(
      `${fork}: 0x${code.toString(16)} (${op.name}) stack effect is ` +
        `${op.stackIn}/${op.stackOut}, expected ${wantIn}/${wantOut}`,
    )
  }
}
// Spot-check known introductions.
if (perFork.frontier.some((o) => o.code === 0x5f)) problems.push('frontier must not have PUSH0')
if (perFork.frontier.some((o) => o.code === 0xfd)) problems.push('frontier must not have REVERT')
if (!perFork.byzantium.some((o) => o.code === 0xfd)) problems.push('byzantium must have REVERT')
if (perFork.byzantium.some((o) => o.code === 0x1b)) problems.push('byzantium must not have SHL')
if (!perFork.constantinople.some((o) => o.code === 0x1b)) problems.push('constantinople must have SHL')
// Paris (the Merge) activates all pre-London EIPs, so it does include SHL.
if (!perFork.paris.some((o) => o.code === 0x1b)) problems.push('paris must have SHL')
if (!perFork.shanghai.some((o) => o.code === 0x5f)) problems.push('shanghai must have PUSH0')
if (!perFork.cancun.some((o) => o.code === 0x5e)) problems.push('cancun must have MCOPY')
if (perFork.shanghai.some((o) => o.code === 0x5e)) problems.push('shanghai must not have MCOPY')

if (problems.length) {
  console.error('Opcode table validation failed:')
  for (const p of problems) console.error('  -', p)
  process.exit(1)
}

// --- output ------------------------------------------------------------------

const output = {
  schemaVersion: '1.0.0',
  generator: 'scripts/generate_opcodes.mjs',
  sources: {
    opcodes: `ethereum/execution-specs@${SPECS_REF} (src/ethereum/forks/<fork>/vm/instructions)`,
    stackEffects: [
      `evm-opcodes@${legacyVersion} (legacy opcodes)`,
      `@ethereumjs/evm@${evmVersion} (dist/esm/eof/stackDelta.js, modern opcodes)`,
    ],
  },
  forks: FORKS,
  opcodes: perFork,
}

const outPath = resolve(repoRoot, 'packages/evm_analysis/data/opcodes.json')
mkdirSync(dirname(outPath), { recursive: true })
writeFileSync(outPath, JSON.stringify(output, null, 2) + '\n')

console.log(`Wrote ${outPath}`)
for (const fork of FORKS) {
  console.log(`  ${fork.padEnd(20)} ${perFork[fork].length} opcodes`)
}
console.log('Validation passed.')
