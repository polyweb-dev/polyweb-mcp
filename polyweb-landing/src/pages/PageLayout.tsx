import type { ReactNode } from "react"

export function PageLayout({
  title,
  intro,
  children,
}: {
  title: string
  intro: ReactNode
  children: ReactNode
}) {
  return (
    <div className="page section-night" data-theme="night">
      <div className="container page-inner">
        <h1 className="page-title">{title}</h1>
        <p className="page-intro">{intro}</p>
        {children}
      </div>
    </div>
  )
}

export function PageSection({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section className="page-section">
      <h2>{title}</h2>
      {children}
    </section>
  )
}
