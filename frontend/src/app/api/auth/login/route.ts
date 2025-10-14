import { NextRequest, NextResponse } from "next/server";

// Proxy to identity service /identity/v4/token
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const res = await fetch("/api/identity/identity/v4/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json({ error: data?.detail || "Login failed" }, { status: res.status });
    }

    const token = data.token as string;
    const csrf = crypto.randomUUID();

    const response = NextResponse.json({ ok: true, token_type: data.token_type, expires_at: data.expires_at });
    response.cookies.set("auth_token", token, { httpOnly: true, sameSite: "lax", secure: true, path: "/" });
    response.cookies.set("csrf_token", csrf, { httpOnly: false, sameSite: "lax", secure: true, path: "/" });
    return response;
  } catch (e: any) {
    return NextResponse.json({ error: e?.message || "Unexpected error" }, { status: 500 });
  }
}


