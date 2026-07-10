// Frontend component-test config.
// Uses babel-jest with inline presets (no root babel.config.js, so Next's own
// SWC build pipeline is untouched). Handles @/ alias via moduleNameMapper.
/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: "jsdom",
  testMatch: ["**/__tests__/**/*.test.tsx", "**/__tests__/**/*.test.ts"],
  transform: {
    "^.+\\.(ts|tsx|js|jsx|mjs)$": [
      "babel-jest",
      {
        presets: [
          ["@babel/preset-env", { targets: { node: "current" } }],
          "@babel/preset-typescript",
          ["@babel/preset-react", { runtime: "automatic" }],
        ],
      },
    ],
  },
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
    // Tauri API stubs for jsdom.
    "^@tauri-apps/api(.*)$": "<rootDir>/__tests__/__mocks__/tauri-mock.cjs",
    // dompurify ships ESM by default; jest's CJS loader needs the CJS build.
    "^dompurify$": "<rootDir>/node_modules/dompurify/dist/purify.cjs.js",
  },
  // Transform the ESM-only deps we actually pull in (framer-motion, lucide,
  // markdown libs). Everything else in node_modules stays ignored.
  transformIgnorePatterns: [
    "/node_modules/(?!(framer-motion|motion-dom|motion-utils|lucide-react|react-markdown|remark-gfm)/)",
  ],
}
