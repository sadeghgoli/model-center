import { NextResponse } from "next/server";

const api = process.env.API_INTERNAL_URL ?? "http://localhost:9005";

export async function POST(request: Request) {
  const payload = await request.json();
  const result = await fetch(`${api}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await result.json();
  const response = NextResponse.json(body, { status: result.status });
  if (body.success && body.data?.access_token) {
    response.cookies.set("mc_access", body.data.access_token, { httpOnly: true, sameSite: "lax", path: "/" });
    response.cookies.set("mc_refresh", body.data.refresh_token, { httpOnly: true, sameSite: "lax", path: "/" });
  }
  return response;
}
