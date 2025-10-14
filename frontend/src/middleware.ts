import { NextResponse, NextRequest } from "next/server";

const PROTECTED_PREFIXES = ["/admin", "/merchant", "/app"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (!PROTECTED_PREFIXES.some((p) => pathname.startsWith(p))) return NextResponse.next();

  const token = req.cookies.get("auth_token")?.value;
  if (!token) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/admin/:path*", "/merchant/:path*", "/app/:path*"],
};


