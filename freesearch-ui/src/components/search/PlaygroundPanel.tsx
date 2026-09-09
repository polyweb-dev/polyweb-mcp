import type { ReactNode } from "react"

type PlaygroundPanelOptions =
  | {
      testId: "search-layout"
      hasSearchContent: boolean
      error: string | null
      children: ReactNode
    }
  | {
      testId: "fetch-layout"
      hasFetchContent: boolean
      error: string | null
      children: ReactNode
    }

export function PlaygroundPanel(options: PlaygroundPanelOptions) {
  const { testId, error, children } = options
  const hasSearchContent =
    "hasSearchContent" in options ? options.hasSearchContent : false
  const hasFetchContent =
    "hasFetchContent" in options ? options.hasFetchContent : false
  const hasContent = hasSearchContent || hasFetchContent
  const layoutClassName = `transition-all duration-300 ease-out motion-reduce:transition-none ${
    hasContent
      ? "top-docked"
      : "w-full mx-auto flex flex-1 min-h-[55vh] max-w-3xl flex-col justify-center"
  }`
  const layout =
    testId === "search-layout" ? (
      <div
        data-testid="search-layout"
        data-state={hasSearchContent ? "docked" : "hero"}
        className={layoutClassName}
      >
        {children}
      </div>
    ) : (
      <div
        data-testid="fetch-layout"
        data-state={hasFetchContent ? "docked" : "hero"}
        className={layoutClassName}
      >
        {children}
      </div>
    )

  return (
    <>
      {layout}
      {error && (
        <p className="text-[13px]" style={{ color: "var(--status-danger)" }}>
          {error}
        </p>
      )}
    </>
  )
}
