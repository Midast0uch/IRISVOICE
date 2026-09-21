/**
 * dev-servers — starts the two frontend dev servers the one Tauri app needs.
 *
 *   :3000  Next.js  — the widget window
 *   :8080  Vite     — the launcher window
 *
 * The launcher used to be a separate Tauri application with its own
 * beforeDevCommand. Now that both windows belong to one app, one
 * beforeDevCommand has to bring up both servers, and Tauri waits on devUrl
 * (:3000) before it opens any window.
 *
 * Vite is started FIRST because Next.js is much slower to become ready, so by
 * the time Tauri stops waiting on :3000 the launcher window has a server to
 * load. It stays in the foreground because Tauri treats the exit of
 * beforeDevCommand as the end of the dev session.
 */
import { spawn, spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// Relocate the Next.js `.next` cache off the slow project drive BEFORE Next
// starts. On the project drive Turbopack's dev cache bloats to ~100k+ files
// under Defender realtime scanning; next-server then holds ~50-100k handles at
// ~0 CPU and answers NOTHING (TCP connects, HTTP hangs) — the "frontend wedge".
//
// This runs here as well as in iris_process_manager so BOTH launch paths
// self-heal: `npm run iris:start:frontend` (manager) and Tauri dev
// (`beforeDevCommand: npm run dev:servers`, this file). Without it, Tauri dev
// would re-bloat the cache on the slow drive. The script is idempotent (a no-op
// once the junction exists) and also ensures the cache-root node_modules shim
// that Node's module resolution needs. Best-effort: never block startup.
const setupScript = path.join(root, 'scripts', 'setup_fast_next_cache.py')
const pythonCandidates = [
  path.join(root, 'venv', 'Scripts', 'python.exe'), // project venv (Windows)
  path.join(root, 'venv', 'bin', 'python'), // project venv (POSIX)
  'python',
  'python3',
]
for (const python of pythonCandidates) {
  const result = spawnSync(python, [setupScript], { stdio: 'ignore' })
  if (result.status === 0) break
  if (result.error && result.error.code === 'ENOENT') continue // interpreter missing
  break // ran but failed — best-effort, do not retry every candidate
}

const servers = [
  {
    name: 'launcher',
    cmd: process.execPath,
    args: [
      path.join(root, 'iris-launcher', 'node_modules', 'vite', 'bin', 'vite.js'),
      '--port',
      '8080',
      '--strictPort',
    ],
    cwd: path.join(root, 'iris-launcher'),
  },
  {
    name: 'widget',
    cmd: process.execPath,
    args: [path.join(root, 'node_modules', 'next', 'dist', 'bin', 'next'), 'dev', '--port', '3000'],
    cwd: root,
  },
]

const children = []
let shuttingDown = false

/** Kill every child once, whichever way this process is asked to end. */
function shutdown(code) {
  if (shuttingDown) return
  shuttingDown = true
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) {
      // On Windows a plain kill() leaves the server's own grandchildren behind,
      // which then hold :3000 and :8080 and make the next run fail on
      // strictPort. taskkill /T takes the whole tree.
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
      } else {
        child.kill('SIGTERM')
      }
    }
  }
  process.exit(code ?? 0)
}

for (const server of servers) {
  const child = spawn(server.cmd, server.args, {
    cwd: server.cwd,
    stdio: 'inherit',
    env: process.env,
  })
  child.on('exit', (code) => {
    // One server dying makes the app half-broken in a way that is confusing to
    // debug from inside a Tauri window, so take the whole thing down and say
    // which half went.
    console.error(`[dev-servers] ${server.name} exited with code ${code}`)
    shutdown(code ?? 1)
  })
  children.push(child)
}

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => shutdown(0))
}
process.on('exit', () => shutdown(0))
