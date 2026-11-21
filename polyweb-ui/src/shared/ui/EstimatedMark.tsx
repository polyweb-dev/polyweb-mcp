/**
 * The "~" in front of an amount estimated from the catalog price. Screen
 * readers hear "Estimated" instead. The hidden word comes first, so the text
 * of the element still contains "~$0.05", and the space between them collapses
 * on screen because the hidden word takes no room in the line.
 */
export function EstimatedMark() {
  return (
    <>
      <span className="sr-only">Estimated</span>{" "}
      <span aria-hidden="true">~</span>
    </>
  )
}
