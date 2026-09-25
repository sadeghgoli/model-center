export async function api(path: string, init: RequestInit = {}) {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (response.status === 401 && typeof window !== "undefined" && path.startsWith("/api/backend")) {
    window.location.assign("/login");
  }
  return { status: response.status, body };
}
