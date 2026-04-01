const isProd = process.env.NODE_ENV === 'production';

/** @type {import('next').NextConfig} */
const nextConfig = {
  // distDir/output only apply to production builds (next build).
  // Dev mode (Turbopack) must not use static export — it needs a live server.
  ...(isProd ? { distDir: 'dist', output: 'export' } : {}),
  compress: true,
  productionBrowserSourceMaps: false,
  typescript: {
    ignoreBuildErrors: false,
  },
  images: {
    unoptimized: true,
  },
  experimental: {
    // optimizePackageImports enables barrel-import tree-shaking so only used
    // icons/components are bundled instead of the entire library.
    // framer-motion, rxjs, and lodash are heavy; tree-shaking them cuts
    // cold-start parse time significantly.
    optimizePackageImports: [
      'lucide-react',
      'framer-motion',
      'motion-dom',
      'motion-utils',
      'rxjs',
      'lodash',
      'zod',
    ],
  },
  compiler: {
    removeConsole: { exclude: ['error'] },
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
      // Exclude backend Python files, session data, and model weights.
      // The [/\\] character class matches both / (Unix) and \ (Windows).
      ignored: /[/\\](node_modules|\.git|\.next|dist|backend|models)[/\\]/,
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

    return config;
  },

  // Turbopack configuration (used by default in Next.js 16 dev).
  //
  // Turbopack is lazy — it only compiles what is actually imported.  It also
  // respects .gitignore for file watching.  Both together mean the 18 GB+
  // models/ and backend/voice/pretrained_models/ directories are never
  // touched at startup, giving near-instant first compile regardless of
  // which worktree the project is opened from.
  //
  // The webpack: callback below still runs for `next build` (production).
  turbopack: {},
};

export default nextConfig;
