import { useContext } from "react"
import { FreeSearchContext } from "./context"

export const useFreeSearch = () => {
  const context = useContext(FreeSearchContext)
  if (!context) {
    throw new Error("useFreeSearch must be used within a FreeSearchProvider")
  }
  return context
}
