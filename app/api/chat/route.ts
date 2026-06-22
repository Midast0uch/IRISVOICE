import { NextRequest, NextResponse } from "next/server"

const BACKEND_URL = process.env.IRIS_BACKEND_URL || "http://localhost:8090"

/**
 * Proxy POST /api/chat to the IRIS backend.
 *
 * The Next.js rewrite in next.config.mjs normally handles this, but this
 * explicit route acts as a fallback and keeps the request on the same origin
 * so the browser doesn't need CORS configuration.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json()

    const res = await fetch(`${BACKEND_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })

    const data = await res.json().catch(() => ({ error: "Invalid JSON from backend" }))

    if (!res.ok) {
      // Forward the backend's FULL error envelope so the caller sees WHY the
      // request failed, not just the error code. The backend returns
      // { ok: false, error: "<code>", message: "<human-readable reason>" }
      // on failure (see backend/api/chat.py). Previously this re-wrapped the
      // body as { error, status } and dropped `message`, so the user only ever
      // saw "internal_error" with no clue about the underlying cause.
      return NextResponse.json(
        { ...data, status: res.status } as any,
        { status: res.status }
      )
    }

    return NextResponse.json(data)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    console.error("[POST /api/chat] proxy error:", message)
    return NextResponse.json({ error: message }, { status: 500 })
  }
}
