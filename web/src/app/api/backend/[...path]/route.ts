import { NextResponse, type NextRequest } from "next/server";
import {
  ACCESS_COOKIE,
  API_URL,
  REFRESH_COOKIE,
  clearSession,
  hasCsrfHeader,
  refreshTokens,
  setSession,
  type TokenPair,
} from "@/lib/server/session";

/**
 * Authenticated pass-through to the FastAPI service. Adds the bearer token from the
 * httpOnly cookie; when the access token has expired, rotates the refresh token once and
 * retries, so the browser never handles a token.
 */
async function forward(request: NextRequest, path: string[], accessToken?: string) {
  const url = new URL(`${API_URL}/api/v1/${path.map(encodeURIComponent).join("/")}`);
  url.search = request.nextUrl.search;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);
  const hasBody = !["GET", "HEAD"].includes(request.method);
  return fetch(url, {
    method: request.method,
    headers,
    body: hasBody ? await request.clone().arrayBuffer() : undefined,
    cache: "no-store",
  });
}

function relay(upstream: Response): NextResponse {
  const headers = new Headers();
  for (const name of ["content-type", "content-disposition", "retry-after"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

async function handle(request: NextRequest, ctx: RouteContext<"/api/backend/[...path]">) {
  const { path } = await ctx.params;
  if (!["GET", "HEAD"].includes(request.method) && !hasCsrfHeader(request)) {
    return NextResponse.json({ detail: "Missing CSRF header" }, { status: 403 });
  }

  let upstream = await forward(request, path, request.cookies.get(ACCESS_COOKIE)?.value);
  if (upstream.status !== 401) return relay(upstream);

  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  const tokens: TokenPair | null = refresh ? await refreshTokens(refresh) : null;
  if (!tokens) {
    const response = relay(upstream);
    clearSession(response);
    return response;
  }
  upstream = await forward(request, path, tokens.access_token);
  const response = relay(upstream);
  setSession(response, tokens);
  return response;
}

export { handle as GET, handle as POST, handle as PATCH, handle as PUT, handle as DELETE };
