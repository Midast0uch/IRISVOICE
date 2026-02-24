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
      ignored: ['**/models/**', '**/node_modules/**', '**/.git/**', '**/.next/**']
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
  // Disable Turbopack explicitly - use webpack for compatibility
  turbopack: {},
}

export default nextConfig
