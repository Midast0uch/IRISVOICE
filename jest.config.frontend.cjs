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
  testPathIgnorePatterns: ["/node_modules/", "/.iris-worktree/", "/.claude/worktrees/", "/llama\\.cpp", "/llama\\.cpp-prismml/", "/llama\\.cpp-turboquant/"],
  // jest-haste-map walks the whole rootDir to build its file map, and on Windows (no watchman) it re-walks it on
  // every run. testPathIgnorePatterns does NOT stop that walk; modulePathIgnorePatterns does (it is the map's ignore
  // pattern, applied while walking). Measured 2026-10-21: `jest --listTests` did not finish in 10 min on the C: hard
  // disk, walking the Python venvs, data/, src-tauri/target, the llama.cpp trees, 25 worktree copies under
  // .claude/worktrees and the .next junction into the Next cache. No frontend module or test lives in these folders
  // (every test is under __tests__/), so the walk skips them.
  modulePathIgnorePatterns: [
    "<rootDir>/(\\.claude|\\.commandcode|\\.git|\\.iris-[^/]*|\\.mcm|\\.next|\\.opencode|\\.playwright-mcp|\\.pytest_cache|\\.ruff_cache|\\.venv|\\.workbuddy-ai|\\.zcode|IRISVOICE|MagicMock|backend|benchmarks|bootstrap|data|dist|docs|evals|evidence|iris-launcher|llama[^/]*|logs|models|notes|prototype|research|screenshots|specs|src-tauri|test-results|tests|venv|verification|__pycache__)/",
  ],
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
