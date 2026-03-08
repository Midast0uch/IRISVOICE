/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: 'dist',
  compress: true,
  productionBrowserSourceMaps: false,
  typescript: {
    ignoreBuildErrors: false,
  },
  images: {
    unoptimized: true,
  },
  experimental: {
    optimizePackageImports: ['lucide-react'],
  },
  compiler: {
    removeConsole: { exclude: ['error'] },
  },
  // Limit webpack memory and caching
  webpack: (config, { isServer }) => {
    // Exclude models directory from webpack processing and watching
    // Models are loaded lazily by the backend on-demand (see backend/agent/lfm_audio_manager.py)
    // This prevents memory spikes (7000+ MB) and extended freeze times during dev mode startup
    config.watchOptions = {
      ...config.watchOptions,
      // Exclude backend Python files and session data — they are never frontend source
      // Backend session JSON files (backend/sessions/**) are written at runtime and
      // would otherwise trigger constant Hot Module Replacement rebuilds.
      // Use a RegExp (not glob strings or a function) — webpack 5 only accepts
      // string | string[] | RegExp for watchOptions.ignored.
      // The character class [/\\] matches both forward-slash (Unix) and
      // backslash (Windows) so this works cross-platform without path normalisation.
      ignored: /[/\\](node_modules|\.git|\.next|dist|backend|models)[/\\]/,
    };
    
    // Exclude model files from webpack asset processing
    // Model file types (.bin, .safetensors) should not be processed by webpack
    config.module.rules.push({
      test: /\.(bin|safetensors)$/,
      type: 'javascript/auto',
      exclude: /models\//,
    });
    
    if (!isServer) {
      config.optimization = {
        ...config.optimization,
        moduleIds: 'named',
        chunkIds: 'named',
      };
    }
    return config;
  },
  // Next.js 16 enables Turbopack by default. We run with `next dev --webpack`
  // (see .claude/launch.json) so webpack's watchOptions.ignored above can exclude
  // backend/sessions/*.json — preventing constant HMR rebuilds from backend writes.
  // turbopack: {} silences the "webpack config without turbopack config" warning.
  turbopack: {},
}

export default nextConfig
