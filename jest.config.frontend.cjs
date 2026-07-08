// Frontend component-test config.
// Uses @swc/jest for TS/TSX transform (next/jest's SWC binary is
// platform-missing in this Next 16 install). Handles @/ alias via
// moduleNameMapper.
/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: "jsdom",
  testMatch: ["**/__tests__/**/*.test.tsx", "**/__tests__/**/*.test.ts"],
  transform: {
    "^.+\\.tsx?$": "babel-jest",
  },
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
    // Tauri API stubs for jsdom.
    "^@tauri-apps/api(.*)$": "<rootDir>/__tests__/__mocks__/tauri-mock.cjs",
  },
  transformIgnorePatterns: ["/node_modules/(?!(framer-motion|motion-dom|motion-utils)/)"],
}
