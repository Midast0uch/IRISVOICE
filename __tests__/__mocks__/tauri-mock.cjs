// Stub for @tauri-apps/api (and subpaths) under jsdom. Returns a jest fn for
// any accessed property so component imports that pull in Tauri never crash.
module.exports = new Proxy(
  {},
  {
    get: () => {
      const fn = () => Promise.resolve()
      fn.listen = () => Promise.resolve(() => {})
      fn.invoke = () => Promise.resolve()
      return fn
    },
  }
)
