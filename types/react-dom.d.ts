declare module "react-dom" {
  export function render(element: any, container: any): void
  export function hydrate(element: any, container: any): void
  export function createPortal(children: any, container: any): any
  export function flushSync(fn: () => void): void
  export function unstable_batchedUpdates(fn: () => void): void
}
