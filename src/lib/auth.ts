import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { verifySessionToken, type SessionUser } from "@/lib/session";

export type Role = "ADMIN" | "EDITOR" | "VIEWER";

export interface AuthContext {
  user: {
    id: string;
    name: string;
    role: Role;
    mustChangePassword: boolean;
  };
}

/**
 * Reads the session cookie from the request, verifies it and loads the
 * current user from the database. Returns null when there is no valid
 * session. Used by every protected API route.
 */
export async function getAuthContext(
  req: NextRequest,
): Promise<AuthContext | null> {
  const token = req.cookies.get("mw_session")?.value;
  if (!token) return null;

  const payload = await verifySessionToken(token);
  if (!payload) return null;

  const user = await db.user.findUnique({
    where: { id: payload.sub },
    select: {
      id: true,
      name: true,
      role: true,
      mustChangePassword: true,
    },
  });

  if (!user) return null;

  return {
    user: {
      id: user.id,
      name: user.name,
      role: user.role as Role,
      mustChangePassword: user.mustChangePassword,
    },
  };
}

/**
 * Guards a route so that only authenticated users may access it. Returns
 * either the auth context or a 401 NextResponse.
 */
export async function requireAuth(
  req: NextRequest,
): Promise<AuthContext | NextResponse> {
  const ctx = await getAuthContext(req);
  if (!ctx) {
    return NextResponse.json({ error: "Nicht angemeldet." }, { status: 401 });
  }
  return ctx;
}

/**
 * Guards a route so that only users with one of the given roles may access
 * it. Returns either the auth context or a 401/403 NextResponse.
 */
export async function requireRole(
  req: NextRequest,
  roles: Role[],
): Promise<AuthContext | NextResponse> {
  const auth = await requireAuth(req);
  if (auth instanceof NextResponse) return auth;
  if (!roles.includes(auth.user.role)) {
    return NextResponse.json(
      { error: "Keine Berechtigung für diese Aktion." },
      { status: 403 },
    );
  }
  return auth;
}

/**
 * Helper used after a successful login/change-password to write the session
 * cookie onto a NextResponse.
 */
export function withSessionCookie(
  res: NextResponse,
  token: string,
): NextResponse {
  res.cookies.set("mw_session", token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 60 * 60 * 24 * 7, // 7 days
  });
  return res;
}

export function clearSessionCookie(res: NextResponse): NextResponse {
  res.cookies.set("mw_session", "", {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  return res;
}

export type { SessionUser };
