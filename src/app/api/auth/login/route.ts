import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { verifyPassword } from "@/lib/password";
import { createSessionToken } from "@/lib/session";
import { withSessionCookie } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/auth/login
 * Body: { name, password }
 *
 * Authenticates a user and sets a signed session cookie. Returns the public
 * user profile (without the password hash). The frontend uses the
 * `mustChangePassword` flag to decide whether to show the force-change
 * password screen.
 */
export async function POST(req: NextRequest) {
  let body: { name?: unknown; password?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Ungültige Anfrage." }, { status: 400 });
  }

  const name = typeof body.name === "string" ? body.name.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";

  if (!name || !password) {
    return NextResponse.json(
      { error: "Bitte Name und Passwort eingeben." },
      { status: 400 },
    );
  }

  const user = await db.user.findUnique({ where: { name } });

  // Always run a hash comparison to keep timing roughly constant even when
  // the user does not exist.
  const dummyHash = "$2a$12$000000000000000000000000000000000000000000000000000000";
  const ok = await verifyPassword(password, user?.passwordHash ?? dummyHash);

  if (!user || !ok) {
    return NextResponse.json(
      { error: "Name oder Passwort ist falsch." },
      { status: 401 },
    );
  }

  const token = createSessionToken({
    sub: user.id,
    name: user.name,
    role: user.role as "ADMIN" | "EDITOR" | "VIEWER",
  });

  const res = NextResponse.json({
    user: {
      id: user.id,
      name: user.name,
      role: user.role,
      mustChangePassword: user.mustChangePassword,
    },
  });
  return withSessionCookie(res, token);
}
