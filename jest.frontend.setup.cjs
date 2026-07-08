// Frontend component-test setup (loaded via jest.config.frontend.cjs).
require("@testing-library/jest-dom")

const React = require("react")

// Deterministic jsdom rendering: replace framer-motion's animated primitives
// with plain elements so layout/animation measurement never flakes in tests.
jest.mock("framer-motion", () => {
  const motion = new Proxy(
    {},
    {
      get: (_target, tag) =>
        React.forwardRef((props, ref) => {
          const { children, ...rest } = props || {}
          return React.createElement(tag, { ...rest, ref }, children)
        }),
    }
  )
  return {
    motion,
    AnimatePresence: ({ children }) => React.createElement(React.Fragment, null, children),
  }
})
