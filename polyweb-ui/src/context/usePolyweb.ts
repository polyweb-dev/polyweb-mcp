import { useContext } from "react"
import { PolywebContext } from "./context"

export const usePolyweb = () => {
  const context = useContext(PolywebContext)
  if (!context) {
    throw new Error("usePolyweb must be used within a PolywebProvider")
  }
  return context
}
