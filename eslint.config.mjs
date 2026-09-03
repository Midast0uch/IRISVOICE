import tsParser from "@typescript-eslint/parser";
import tsPlugin from "@typescript-eslint/eslint-plugin";
import reactHooks from "eslint-plugin-react-hooks";

// Flat config for ESLint 10 (Next.js 16 project).
// Uses the already-installed @typescript-eslint v8 parser + plugin.
// NOTE: eslint-config-next is not installed, so Next.js-specific rules are
// not applied here — this config focuses on TypeScript/React correctness.
export default [
  {
    files: ["**/*.{ts,tsx,js,jsx,mjs,cjs}"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "react-hooks": reactHooks,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      // Relax a couple of rules that are noisy in this codebase but not bugs.
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-empty-object-type": "off",
      "@typescript-eslint/no-namespace": "off",
      "@typescript-eslint/ban-ts-comment": "off",
      // react-hooks: define the rule so existing eslint-disable comments resolve.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "build/**",
      "dist/**",
      "coverage/**",
      // Vendored third-party projects with their own (broken) nested eslint
      // configs — not part of this app, exclude from `eslint .`.
      "llama.cpp/**",
      "llama-cpp-turboquant/**",
    ],
  },
];
