/**
 * Plain words for the personal task card (owner, 2026-10-06): the engine's words never
 * reach the screen. The card says "looked closer" (a sub-loop split), "done" (converged /
 * crystallized) and "reported back" (a fold-back). Pure; the matrix already speaks this way
 * (components/chat/matrix/matrixModel.ts).
 */
export const LOOKED_CLOSER = "looked closer"
export const REPORTED_BACK = "reported back"

export function plainWords(text: string): string {
  return (text || "")
    .replace(/\bsub[-\s]?loops?\b/gi, LOOKED_CLOSER)
    .replace(/\bdiving deeper\b/gi, LOOKED_CLOSER)
    .replace(/\bfold[-\s]?backs?\b/gi, REPORTED_BACK)
    .replace(/\bconverge[sd]?\b|\bconvergence\b/gi, "done")
    .replace(/\bcrystalliz(?:e|es|ed|ing|ation)\b/gi, "done")
    .replace(/\blandmarks?\b/gi, "note")
}
