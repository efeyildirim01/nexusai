import { NextResponse, type NextRequest } from "next/server";

/** Optimistic check only: send visitors without a session to sign-in. Real authorization
 * happens in the API on every request. */
export function proxy(request: NextRequest) {
  const signedIn = request.cookies.has("nx_session");
  const { pathname, search } = request.nextUrl;
  if (pathname.startsWith("/app") && !signedIn) {
    const url = new URL("/sign-in", request.url);
    url.searchParams.set("next", pathname + search);
    return NextResponse.redirect(url);
  }
  if ((pathname === "/sign-in" || pathname === "/sign-up") && signedIn) {
    return NextResponse.redirect(new URL("/app", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/app/:path*", "/sign-in", "/sign-up"],
};
