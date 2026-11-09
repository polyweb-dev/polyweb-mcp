import "@testing-library/react"

declare module "@testing-library/react" {
  interface ByRoleOptions {
    /** Compatibility with the exact option accepted by the runtime query helpers. */
    exact?: boolean
  }
}
