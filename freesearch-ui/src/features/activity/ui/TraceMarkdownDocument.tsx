import { Fragment, type ReactNode } from "react"

/** Untrusted document links stay inert unless they use HTTP or HTTPS. */
function documentLink(target: string, baseUrl: string): string | undefined {
  try {
    const url = new URL(target, baseUrl)
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : undefined
  } catch {
    return undefined
  }
}

function inlineText(text: string, baseUrl: string): ReactNode {
  const tokens = /(!?\[([^\]]+)\]\(([^\s)]+)(?:\s+"[^"]*")?\)|\*\*([^*]+)\*\*|`([^`]+)`|\*([^*]+)\*)/g
  const nodes: ReactNode[] = []
  let end = 0
  for (const match of text.matchAll(tokens)) {
    nodes.push(text.slice(end, match.index))
    const [token, , label, target, bold, code, emphasis] = match
    let node: ReactNode = token
    if (label !== undefined && target !== undefined) {
      const href = documentLink(target, baseUrl)
      node = href && !token.startsWith("!")
        ? <a href={href} target="_blank" rel="noreferrer" className="fs-link">{label}</a>
        : label
    } else if (bold !== undefined) node = <strong className="font-medium text-[var(--text-strong)]">{bold}</strong>
    else if (code !== undefined) node = <code className="mono rounded bg-[var(--raised)] px-1">{code}</code>
    else if (emphasis !== undefined) node = <em>{emphasis}</em>
    nodes.push(<Fragment key={match.index}>{node}</Fragment>)
    end = match.index + token.length
  }
  nodes.push(text.slice(end))
  return nodes
}

function textBlock(lines: string[], baseUrl: string): ReactNode {
  const first = lines[0] ?? ""
  const heading = /^(#{1,6})\s+(.+)$/.exec(first)
  if (heading) {
    const Tag = `h${heading[1]!.length}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6"
    return <Tag className="text-[15px] font-medium text-[var(--text-strong)]">{inlineText(heading[2]!, baseUrl)}</Tag>
  }
  if (/^\s*([-*+] |\d+\. )/.test(first)) {
    const Tag = /^\s*\d+\./.test(first) ? "ol" : "ul"
    return <Tag className={`space-y-1 pl-5 ${Tag === "ol" ? "list-decimal" : "list-disc"}`}>
      {lines.map((line, index) => <li key={index}>{inlineText(line.replace(/^\s*(?:[-*+]|\d+\.)\s+/, ""), baseUrl)}</li>)}
    </Tag>
  }
  if (/^>\s?/.test(first)) return <blockquote className="border-l-2 border-[var(--border-subtle)] pl-3 text-[var(--muted)]">{inlineText(lines.map((line) => line.replace(/^>\s?/, "")).join("\n"), baseUrl)}</blockquote>
  if (/^\s*(?:---+|\*\*\*+)\s*$/.test(first)) return <hr className="border-[var(--border-subtle)]" />
  return <p className="whitespace-pre-wrap">{inlineText(lines.join("\n"), baseUrl)}</p>
}

/** A text-only Markdown view: no embedded HTML or remote image execution. */
export function TraceMarkdownDocument({ content, url }: { content: string; url: string }) {
  const blocks: ReactNode[] = []
  let lines: string[] = []
  let fence: string | null = null
  const flush = () => {
    if (lines.length === 0) return
    blocks.push(<Fragment key={blocks.length}>{fence === null
      ? textBlock(lines, url)
      : <pre className="mono overflow-x-auto rounded bg-[var(--surface)] p-3 text-[12px]"><code>{lines.join("\n")}</code></pre>}</Fragment>)
    lines = []
  }
  for (const line of content.split(/\r?\n/)) {
    const marker = /^\s*(```+|~~~+)/.exec(line)?.[1]
    if (marker && (fence === null || marker.startsWith(fence))) {
      flush()
      fence = fence === null ? marker : null
    } else if (fence !== null) lines.push(line)
    else if (line.trim() === "") flush()
    else if (/^#{1,6}\s/.test(line)) {
      flush()
      lines.push(line)
      flush()
    } else lines.push(line)
  }
  flush()
  return <div className="min-w-0 space-y-4 text-[13px] leading-relaxed [overflow-wrap:anywhere]">{blocks}</div>
}
