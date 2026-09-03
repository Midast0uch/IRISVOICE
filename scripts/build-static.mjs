/**
 * build-static — produce the frontend bundle the packaged Tauri app ships.
 *
 * tauri.conf.json points frontendDist at ../dist and its beforeBuildCommand
 * runs this. Two halves land there, in this order and for this reason:
 *
 *   1. next build, with IRIS_STATIC_EXPORT=1, which makes next.config.mjs turn
 *      on `output: 'export'` and write to dist/. It owns dist/ and clears it.
 *   2. vite build in iris-launcher, which writes dist/launcher/. It MUST run
 *      second: the Next build would otherwise wipe it.
 *
 * The flag is set here rather than in the npm script because Windows and POSIX
 * shells disagree about `VAR=1 cmd`, and adding cross-env for one variable is
 * a dependency this does not need.
 */
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const steps = [
  {
    name: 'widget (next export)',
    cmd: process.execPath,
    args: [path.join(root, 'node_modules', 'next', 'dist', 'bin', 'next'), 'build'],
    cwd: root,
    env: { ...process.env, IRIS_STATIC_EXPORT: '1' },
  },
  {
    name: 'launcher (vite)',
    cmd: process.execPath,
    args: [path.join(root, 'iris-launcher', 'node_modules', 'vite', 'bin', 'vite.js'), 'build'],
    cwd: path.join(root, 'iris-launcher'),
    env: process.env,
  },
]

for (const step of steps) {
  console.log(`\n[build-static] ${step.name}`)
  const res = spawnSync(step.cmd, step.args, { cwd: step.cwd, env: step.env, stdio: 'inherit' })
  if (res.status !== 0) {
    console.error(`[build-static] ${step.name} failed with code ${res.status}`)
    process.exit(res.status ?? 1)
  }
}

console.log('\n[build-static] dist/ ready — widget at the root, launcher under dist/launcher')
