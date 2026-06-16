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
    /^100\.\d+\.\d+\.\d+$/,
    /\.ts\.net$/,
  ],

  // Backend lives on :8000; let the browser reach it through the same origin
  // so we don't have to fight CORS, and so production builds don't need a
  // separate API base URL.
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8000/api/:path*',
      },
    ];
  },

  // ===========================================================================
  // Webpack exclusions — applies to `next build` (production) only.
  //
  // Dev mode now uses Turbopack (lazy, path-independent cache, respects
  // .gitignore) which avoids the 18GB+ models/ scan entirely.
  //
  // For production builds (`next build`) these exclusions still prevent
  // webpack from scanning model-weight directories.
  //
  // watchOptions.ignored MUST be a RegExp — webpack 5 only processes RegExp
  // correctly here (glob strings are silently ignored on Windows).
  //
  // History: see docs/OPTIMIZATION_LOG.md — February 23, 2026.
  // ===========================================================================
  webpack: (config, { isServer, dev }) => {
    config.watchOptions = {
      ...config.watchOptions,
      // Exclude backend Python files, session data, model weights, and
      // everything outside the app source tree. The [/\\] character class
      // matches both / (Unix) and \ (Windows).
      ignored: /[/\\](node_modules|\.git|\.next|dist|backend|models|llama\.cpp|llama-cpp-turboquant|.iris-logs|.iris-pids|.iris-worktree|.mcm|.venv|venv|tests|e2e|benchmarks|research|specs|verification|hooks|pyinstaller_hooks|app|public|components|lib|contexts|integrations|stores|styles)[/\\]/,
    };

    // Prevent webpack from trying to process model weight files as JS assets.
    config.module.rules.push({
      test: /\.(bin|safetensors|gguf|pt|pth)$/,
      type: 'javascript/auto',
      exclude: /models\//,
    });

    // Named module/chunk IDs aid stack-trace debugging but add significant
    // overhead during dev compilation. Only enable them in production builds.
    if (!isServer && !dev) {
      config.optimization = {
        ...config.optimization,
        moduleIds: 'named',
        chunkIds: 'named',
      };
    }

    // Note: do NOT set config.devtool in dev — Next.js will revert it with
    // a warning ("severe performance regressions"). Next.js picks an
    // appropriate devtool automatically.

    return config;
  },

  // Turbopack configuration (used by default in Next.js 16 dev).
  //
  // NOTE: Turbopack is completely disabled because its PostCSS pipeline
  // (evaluate_webpack_loader) has a hardcoded reference to app/globals.css
  // that always triggers CSS processing. Even with an empty file, the
  // sandboxed loader process times out, causing an infinite retry loop
  // that balloons memory to 12+ GB (uncapped by --max-old-space-size=512).
  // Webpack handles the same CSS file in < 1 second with no memory issue.
  //
  // History: see docs/OPTIMIZATION_LOG.md — June 2026.
  // See also app/layout.tsx note at top.
  turbo: false,
  experimental: {
    // Next 16.2.1+ has a memory regression in Turbopack's server-side fast
    // refresh path that compounds with route navigation; dev server can grow
    // from 200 MB to 8+ GB while idle. Disable until the upstream fix lands.
    // See vercel/next.js#91396 and Discussion #94471.
    turbopackServerFastRefresh: false,
  },
};

export default nextConfig;
