import { NextResponse } from "next/server";
import { getAuthTokenServer, parseJwtServer } from "@/lib/auth";

export async function GET() {
  const token = getAuthTokenServer();
  if (!token) return NextResponse.json({ authenticated: false }, { status: 200 });
  const claims = parseJwtServer(token) || {};
  return NextResponse.json({ authenticated: true, claims }, { status: 200 });
}


