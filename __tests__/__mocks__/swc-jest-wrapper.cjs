// Wrapper for @swc/jest so jest 30 with experimental-vm-modules can
// resolve the transformer from a local file path (it fails to resolve
// node_modules path under ESM resolution).
const { createTransformer } = require("@swc/jest")
const swcConfig = {
  jsc: {
    parser: { syntax: "typescript", tsx: true },
    transform: {
      react: { runtime: "automatic", importSource: "react" },
    },
  },
}
module.exports = createTransformer(swcConfig)
