const isProd = process.env.NODE_ENV === 'production';

// On Windows + slow project drives (e.g. Desktop under OneDrive / antivirus
// real-time scan), Next.js dev compilation in .next can hang for minutes and
// balloon to 1-15 GB. The fix is to relocate the cache off the slow drive
// using a directory junction (see scripts/setup_fast_next_cache.py /
// start-iris.bat) so .next resolves to a fast local path.

/** @type {import('next').NextConfig} */
const nextConfig = {
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
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `http://localhost:${process.env.IRIS_BACKEND_PORT || 8090}/api/:path*`,
      },
    ];
  },

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
