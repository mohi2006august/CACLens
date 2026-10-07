import { NextResponse } from "next/server";

import { API_URL } from "@/lib/api";

// Same-origin proxy for /v1/ask so the browser never needs the API's address or CORS.
export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }
  try {
    const res = await fetch(new URL("/v1/ask", API_URL), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const data: unknown = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json(
      { detail: `Cannot reach the CACLens API at ${API_URL}. Start it with: uv run caclens serve` },
      { status: 502 },
    );
  }
}
