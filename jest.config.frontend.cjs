// Frontend component-test config.
// Uses babel-jest with inline presets (no root babel.config.js, so Next's own
// SWC build pipeline is untouched). Handles @/ alias via moduleNameMapper.
/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: "jsdom",
  testMatch: ["**/__tests__/**/*.test.tsx", "**/__tests__/**/*.test.ts"],
  // Never sweep stale worktree copies (.iris-worktree) or vendored C++ trees:
  // their __tests__ duplicates reference moved modules (temp/ -> lib/cli) and
  // their duplicate manual mocks poison jest-haste-map.
  testPathIgnorePatterns: ["/node_modules/", "/.iris-worktree/", "/llama\\.cpp", "/llama\\.cpp-prismml/", "/llama\\.cpp-turboquant/"],
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
  // Transform the ESM-only deps we actually pull in. react-markdown pulls a whole
  // ESM-only transitive tree (unified/remark/micromark/hast/mdast + devlop), and
  // listing only the direct deps let `devlop` break the InputRow suite at import.
  // Everything else in node_modules stays ignored.
  transformIgnorePatterns: [
    "/node_modules/(?!(framer-motion|motion-dom|motion-utils|lucide-react|react-markdown|remark-.*|rehype-.*|unified|bail|is-plain-obj|trough|vfile.*|unist-util-.*|mdast-util-.*|micromark.*|hast-util-.*|hastscript|property-information|space-separated-tokens|comma-separated-tokens|html-url-attributes|decode-named-character-reference|character-entities.*|zwitch|longest-streak|ccount|escape-string-regexp|markdown-table|trim-lines|devlop|estree-util-.*|style-to-js|style-to-object|inline-style-parser|web-namespaces|stringify-entities)/)",
  ],
}
