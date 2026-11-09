import logo from "../assets/polyweb.webp"
import { GITHUB } from "../links"

const COLUMNS: Array<{
  heading: string
  links: Array<{ label: string; href: string; external?: boolean }>
}> = [
  {
    heading: "Product",
    links: [
      { label: "Providers", href: "#/providers" },
      { label: "Projects and keys", href: "#/projects" },
      { label: "Self-hosting", href: "#/self-hosting" },
      { label: "Security", href: "#/security" },
    ],
  },
  {
    heading: "Developers",
    links: [
      { label: "Search API", href: "#/search-api" },
      { label: "Fetch API", href: "#/fetch-api" },
      { label: "MCP server", href: "#/mcp" },
      { label: "Release notes", href: `${GITHUB}/tree/main/docs/releases`, external: true },
    ],
  },
  {
    heading: "Project",
    links: [
      { label: "About", href: "#/about" },
      { label: "GitHub", href: GITHUB, external: true },
      { label: "Report an issue", href: `${GITHUB}/issues`, external: true },
    ],
  },
]

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <div className="site-footer-brand">
          <span className="site-footer-name">
            <img src={logo} alt="" width={26} height={26} />
            Polyweb
          </span>
          <p className="site-footer-line">
            Self-hosted search and fetch across eight providers.
          </p>
        </div>
        <div className="site-footer-cols">
          {COLUMNS.map((col) => (
            <div className="site-footer-col" key={col.heading}>
              <h3>{col.heading}</h3>
              {col.links.map((link) =>
                link.external ? (
                  <a
                    key={link.label}
                    href={link.href}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {link.label}
                  </a>
                ) : (
                  <a key={link.label} href={link.href}>
                    {link.label}
                  </a>
                )
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="site-footer-bottom">© 2026 Polyweb</div>
    </footer>
  )
}
