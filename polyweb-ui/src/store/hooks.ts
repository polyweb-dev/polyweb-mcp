import { useDispatch, useSelector } from "react-redux"
import type { AppDispatch, RootState } from "./store"

/** Typed store hooks: use these instead of the untyped react-redux originals. */
export const useAppDispatch = useDispatch.withTypes<AppDispatch>()
export const useAppSelector = useSelector.withTypes<RootState>()
