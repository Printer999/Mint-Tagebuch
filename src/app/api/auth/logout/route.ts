import { NextResponse } from "next/server";
import { clearSessionCookie } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/auth/logout
 *
 * Clears the session cookie.
 */
export async function POST() {
  const res = NextResponse.json({ ok: true });
  return clearSessionCookie(res);
}
