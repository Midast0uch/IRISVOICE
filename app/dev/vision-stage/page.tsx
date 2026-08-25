"use client"

/**
 * /dev/vision-stage — standalone route for the Vision Stage Simulator.
 *
 * NOTE: scenarios animate the overlay that lives in the MAIN app tree
 * (CrawlProvider + wings at "/"). CustomEvents do not cross pages, so real
 * sign-off happens with the panel mounted INSIDE the app: open
 * `/?dev=vision-stage`. This route remains as the standalone reference/docs
 * view (fixture frame + checklist still work here).
 */

import { Suspense } from "react"
import { VisionStagePanel } from "@/components/iris/simulator/VisionStagePanel"

export default function VisionStagePage() {
  return (
    <Suspense fallback={null}>
      <VisionStagePanel />
    </Suspense>
  )
}
