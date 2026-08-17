import { NextRequest, NextResponse } from "next/server";
import { getAuthContext } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * GET /api/auth/me
 *
 * Returns the currently authenticated user or 401. Used by the frontend to
 * restore the session after a page reload.
 */
export async function GET(_req: NextRequest) {
  const ctx = await getAuthContext(_req);
  if (!ctx) {
    return NextResponse.json({ user: null }, { status: 200 });
  }
  return NextResponse.json({ user: ctx.user });
}
