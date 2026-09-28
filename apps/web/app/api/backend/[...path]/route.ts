import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

const api = process.env.API_INTERNAL_URL ?? "http://localhost:9005";

async function handle(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const jar = await cookies();
  const access = jar.get("mc_access")?.value;
  const target = `${api}/${path.join("/")}${request.nextUrl.search}`;
  const method = request.method;
  const requestType = request.headers.get("content-type");
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const headers: Record<string, string> = {};
  if (access) headers.Authorization = `Bearer ${access}`;
  if (requestType && body && body.byteLength > 0) headers["Content-Type"] = requestType;
  const response = await fetch(target, {
    method,
    body: body && body.byteLength > 0 ? body : undefined,
    headers,
  });
  const contentType = response.headers.get("content-type") ?? "application/json";
  if (contentType.includes("text/event-stream") && response.body) {
    return new NextResponse(response.body, {
      status: response.status,
      headers: { "Content-Type": contentType, "Cache-Control": "no-cache", "X-Accel-Buffering": "no" },
    });
  }
  const text = await response.text();
  return new NextResponse(text, { status: response.status, headers: { "Content-Type": contentType } });
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
