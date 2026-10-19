import { NextResponse, type NextRequest } from "next/server";
import {
  API_URL,
  REFRESH_COOKIE,
  clearSession,
  hasCsrfHeader,
  setSession,
  type TokenPair,
} from "@/lib/server/session";

const UPSTREAM: Record<string, string> = {
  signin: "/api/v1/auth/login",
  signup: "/api/v1/auth/signup",
  "accept-invite": "/api/v1/auth/invitations/accept",
};

export async function POST(request: NextRequest, ctx: RouteContext<"/api/auth/[action]">) {
  const { action } = await ctx.params;
  if (!hasCsrfHeader(request)) {
    return NextResponse.json({ detail: "Missing CSRF header" }, { status: 403 });
  }

  if (action === "signout") {
    const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
    if (refresh) {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      }).catch(() => undefined);
    }
    const response = NextResponse.json({ ok: true });
    clearSession(response);
    return response;
  }

  const path = UPSTREAM[action];
  if (!path) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  const upstream = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  const body = await upstream.json().catch(() => ({ detail: "Unexpected response" }));
  if (!upstream.ok) {
    return NextResponse.json(body, { status: upstream.status });
  }
  const response = NextResponse.json({ ok: true });
  setSession(response, body as TokenPair);
  return response;
}
