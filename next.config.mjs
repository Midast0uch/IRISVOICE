const isProd = process.env.NODE_ENV === 'production';

/**
 * Static export, for the packaged Tauri widget only.
 *
 * Set by scripts/build-static.mjs, which is what tauri.conf.json's
 * beforeBuildCommand runs. It is a DEDICATED flag rather than NODE_ENV because
 * `next start` is still a supported way to run this app in production, and
 * `output: 'export'` would break it.
 *
 * Two things below are mutually exclusive with an export and are therefore
 * gated on it:
 *   - rewrites(), which has no runtime to execute in a static bundle. The
 *     client keeps working because lib/apiOrigin reinstates the same rewrite
 *     in the browser, where a package still has one.
 *   - next/image optimisation, which needs a server.
 */
const staticExport = process.env.IRIS_STATIC_EXPORT === '1';

// On Windows + slow project drives (e.g. Desktop under OneDrive / antivirus
// real-time scan), Next.js dev compilation in .next can hang for minutes and
// balloon to 1-15 GB.
//
// DO NOT relocate .next via a directory junction (see
// scripts/setup_fast_next_cache.py): attempted 2026-09-05, it cut compiles
// 6.7min -> 2.1min but Turbopack dev resolves externals through `..`-relative
// paths that break across the junction boundary (every page 500s with
// "Cannot find module" for next/dist/compiled/* and react/jsx-runtime).
// Reverted the same day. If slowness returns, look at AV exclusions / drive
// type instead — never re-junction .next.

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Tauri's frontendDist is ../dist, so an export has to land there. A normal
  // build keeps .next untouched.
  ...(staticExport ? { output: 'export', distDir: 'dist', images: { unoptimized: true } } : {}),

  // Allow dev access from 127.0.0.1 (used by phone via Tailscale / QR code)
  allowedDevOrigins: [
    // Local development
    '127.0.0.1', 'localhost', '0.0.0.0',
    // Current Tailscale IP (stable while tailnet is unchanged)
    '100.117.236.6',
    // Any Tailscale IP (100.x.x.x) or MagicDNS hostname (*.ts.net)
    // NOTE: Next.js 16 only accepts strings in allowedDevOrigins, not regex.
    // Add specific Tailscale IPs here as needed.
  ],

  // Backend lives on :8090; let the browser reach it through the same origin
  // so we don't have to fight CORS, and so production builds don't need a
  // separate API base URL.
  // Omitted entirely under a static export — Next.js rejects the combination,
  // and there would be no server to run it anyway.
  ...(staticExport
    ? {}
    : {
        async rewrites() {
          return [
            {
              source: '/api/:path*',
              destination: `http://localhost:${process.env.IRIS_BACKEND_PORT || 8090}/api/:path*`,
            },
            {
              // The IRIS Launcher is a separate Vite app, but its window must
              // share THIS origin. A Tauri window built with an External url is
              // a remote origin and gets no IPC, so the launcher's
              // invoke("launch_widget") was dropped before reaching Rust.
              // Proxying it here lets the window be a WebviewUrl::App on the
              // same origin as the widget, exactly as in a packaged build,
              // where dist/launcher/ is served from the bundle and no proxy is
              // involved. That is why this sits inside the non-export branch.
              source: '/launcher/:path*',
              destination: `http://localhost:${process.env.IRIS_LAUNCHER_PORT || 8080}/launcher/:path*`,
            },
          ];
        },
      }),

  // ===========================================================================
  // NO webpack CONFIG HERE — AND THAT IS DELIBERATE.
  //
  // Next.js 16 builds with Turbopack by default (the banner prints
  // "Next.js <ver> (Turbopack)" on every run, and package.json calls a plain
  // `next build` with no --no-turbopack). A `webpack: (config) => {...}`
  // function is therefore NEVER INVOKED.
  //
  // A block of webpack exclusions used to live here — watchOptions.ignored for
  // models/backend/llama.cpp/venv, a module rule for .gguf/.safetensors/.bin,
  // and moduleIds/chunkIds: 'named'. It was verified dead on 2026-08-25 by
  // inserting a console.log as the function's first statement and running a
  // full build: the marker never printed. Its comment claimed it still applied
  // to production builds; that was false. Removed rather than left as a lie —
  // see specs/dev-cli-ide/GATE0-FINDINGS.md (G0-10).
  //
  // Turbopack honours .gitignore, so heavy directories are excluded THERE, not
  // here. models/gguf, venv, .venv and llama.cpp were added to .gitignore for
  // exactly this reason. If you need to exclude something from the build, add
  // it to .gitignore — adding a webpack() function back will silently do
  // nothing.
  //
  // History: docs/OPTIMIZATION_LOG.md — February 23, 2026 (webpack era).
  // ===========================================================================

  // Turbopack is the default dev bundler in Next.js 16.
  // To disable it (e.g. for CSS issues), pass --no-turbopack to the CLI:
  //   npx next dev --port 3000 --no-turbopack
  // The "turbo" config key was removed in Next.js 16.
  experimental: {
    // Next 16.2.1+ has a memory regression in Turbopack's server-side fast
    // refresh path that compounds with route navigation; dev server can grow
    // from 200 MB to 8+ GB while idle. Disable until the upstream fix lands.
    // See vercel/next.js#91396 and Discussion #94471.
    turbopackServerFastRefresh: false,
  },
};

export default nextConfig;
