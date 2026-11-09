import { Link, type LinkProps } from "react-router"
import { Button } from "./button"

/** Navigation with the same surface and keyboard focus as a secondary action. */
export function LinkButton({ children, to, ...props }: LinkProps) {
  const target = typeof to === "string" && /^https?:\/\//.test(to)
    ? <a href={to} {...props} />
    : <Link to={to} {...props} />
  return (
    <Button variant="outline" size="sm" role="link" nativeButton={false} render={target}>
      {children}
    </Button>
  )
}
