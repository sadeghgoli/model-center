import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const access = request.cookies.get("mc_access")?.value;
  if (!access) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = { matcher: ["/dashboard", "/models/:path*", "/runtimes", "/projects/:path*", "/playground", "/docs"] };
