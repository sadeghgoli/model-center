import { NextRequest, NextResponse } from "next/server";

const api = process.env.API_INTERNAL_URL ?? "http://localhost:9005";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
};

async function handle(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = `${api}/v1/${path.join("/")}${request.nextUrl.search}`;
  const method = request.method;
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const headers: Record<string, string> = {};
  const authorization = request.headers.get("authorization");
  const requestType = request.headers.get("content-type");
  if (authorization) headers.Authorization = authorization;
  if (requestType && body && body.byteLength > 0) headers["Content-Type"] = requestType;
  const response = await fetch(target, {
    method,
    body: body && body.byteLength > 0 ? body : undefined,
    headers,
  });
  return new NextResponse(response.body, {
    status: response.status,
    headers: {
      ...cors,
      "Content-Type": response.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}

export function OPTIONS() {
  return new NextResponse(null, { status: 204, headers: cors });
}

export const GET = handle;
export const POST = handle;
