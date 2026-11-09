import polywebLogo from "@/assets/polyweb.webp"

/** Primary call-to-action classes of the current auth surface. */
export const AUTH_SUBMIT_CLASSES =
  "w-full flex items-center justify-center gap-2 text-[13px] font-medium bg-[var(--signal)] hover:bg-[var(--signal)]/90 text-white h-10 shadow-sm transition-colors"

/** Auth page footer wrapper: the distance sits on the wrapper, not on the text. */
export const AUTH_FOOTER_CLASSES = "mt-6"

/** Auth page footer text and anchor classes of the current surface. */
export const AUTH_FOOTER_TEXT_CLASSES =
  "text-[13px] text-[var(--muted)] *:[a]:underline *:[a]:underline-offset-3 *:[a]:hover:text-[var(--text-strong)]"

/** Visible keyboard focus for a link inside an auth page. */
export const AUTH_LINK_CLASSES =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)]"

/** Field classes of the shared text field, without the numeric variant. */
export const AUTH_FIELD_CLASSES =
  "w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"

/** Brand row classes of the auth pages, in the style of the sidebar brand. */
export const AUTH_BRAND_CLASSES = "mb-6 flex items-center gap-3"
export const AUTH_BRAND_TILE_CLASSES =
  "grid size-12 shrink-0 place-items-center overflow-hidden rounded-lg border border-[var(--border-subtle)] bg-[var(--secondary)]"
export const AUTH_BRAND_NAME_CLASSES =
  "text-[22px] font-semibold tracking-tight text-[var(--text-strong)]"

interface AuthPanelProps {
  title: string
  subtitle?: string
  children: React.ReactNode
}

/**
 * Centered static auth card, plus the shared class contract of the auth pages.
 *
 * The brand row carries the repository logo and the product name above the card,
 * with the same tile, surface, and tracking style as the sidebar brand. The card
 * reuses the elevated surface and shared title size, with 24px between groups
 * and no internal dividers. There is no portal, overlay, or focus trap.
 * The exported class strings keep the
 * two auth pages identical without an import between features.
 */
export function AuthPanel({ title, subtitle, children }: AuthPanelProps) {
  return (
    <div
      className="flex min-h-screen flex-col items-center justify-center p-8"
      style={{ background: "var(--surface)", color: "var(--text)" }}
    >
      <div className={AUTH_BRAND_CLASSES}>
        <span className={AUTH_BRAND_TILE_CLASSES}>
          <img src={polywebLogo} alt="" aria-hidden="true" className="size-9 object-contain" />
        </span>
        <span className={AUTH_BRAND_NAME_CLASSES}>Polyweb</span>
      </div>
      <div
        className="w-full max-w-sm rounded-xl p-6"
        style={{
          background: "var(--elevated)",
          border: "1px solid var(--border-subtle)",
          color: "var(--text)",
        }}
      >
        <div className="flex flex-col gap-1">
          <h1
            className="text-[15px] font-medium"
            style={{ color: "var(--text-strong)", fontSize: "15px" }}
          >
            {title}
          </h1>
          {subtitle && (
            <p className="text-[13px]" style={{ color: "var(--muted)" }}>
              {subtitle}
            </p>
          )}
        </div>
        <div className="mt-6">{children}</div>
      </div>
    </div>
  )
}
