import "server-only";
import type { NextResponse } from "next/server";

/**
 * Backend-for-frontend session. The FastAPI tokens live only in httpOnly cookies, so
 * browser JavaScript (and any XSS) can never read them. Route handlers attach them to
 * calls to the API.
 */
export const API_URL = process.env.NEXUS_API_URL ?? "http://localhost:8000";
export const ACCESS_COOKIE = "nx_at";
export const REFRESH_COOKIE = "nx_rt";
export const CSRF_HEADER = "x-nexus-csrf";

const secure = process.env.NODE_ENV === "production";

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export function setSession(response: NextResponse, tokens: TokenPair): void {
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: tokens.expires_in,
  });
  // The refresh token is only ever needed by the BFF routes under /api.
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    httpOnly: true,
    secure,
    sameSite: "strict",
    path: "/api",
    maxAge: 14 * 24 * 3600,
  });
  // Non-secret marker the proxy can see on page routes (the refresh cookie is scoped to /api).
  response.cookies.set("nx_session", "1", {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: 14 * 24 * 3600,
  });
}

export function clearSession(response: NextResponse): void {
  response.cookies.set(ACCESS_COOKIE, "", { path: "/", maxAge: 0 });
  response.cookies.set(REFRESH_COOKIE, "", { path: "/api", maxAge: 0 });
  response.cookies.set("nx_session", "", { path: "/", maxAge: 0 });
}

/** State-changing requests must carry a custom header. Browsers cannot attach one to a
 * cross-site form post or image load, so this blocks CSRF on top of SameSite cookies. */
export function hasCsrfHeader(request: Request): boolean {
  return request.headers.get(CSRF_HEADER) === "1";
}

export async function refreshTokens(refreshToken: string): Promise<TokenPair | null> {
  const response = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
  return response.ok ? ((await response.json()) as TokenPair) : null;
}
