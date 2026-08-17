import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { hashPassword, verifyPassword } from "@/lib/password";
import { getAuthContext } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * POST /api/auth/change-password
 * Body: { currentPassword, newPassword }
 *
 * Lets the authenticated user change their password. Clears the
 * `mustChangePassword` flag so the force-change screen is no longer shown.
 * Used both for the first-login flow and for voluntary password changes.
 */
export async function POST(req: NextRequest) {
  const ctx = await getAuthContext(req);
  if (!ctx) {
    return NextResponse.json({ error: "Nicht angemeldet." }, { status: 401 });
  }

  let body: { currentPassword?: unknown; newPassword?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Ungültige Anfrage." }, { status: 400 });
  }

  const currentPassword =
    typeof body.currentPassword === "string" ? body.currentPassword : "";
  const newPassword = typeof body.newPassword === "string" ? body.newPassword : "";

  if (!currentPassword || !newPassword) {
    return NextResponse.json(
      { error: "Bitte altes und neues Passwort eingeben." },
      { status: 400 },
    );
  }

  if (newPassword.length < 4) {
    return NextResponse.json(
      { error: "Das neue Passwort muss mindestens 4 Zeichen lang sein." },
      { status: 400 },
    );
  }

  if (newPassword === "1234") {
    return NextResponse.json(
      { error: "Das neue Passwort darf nicht 1234 sein." },
      { status: 400 },
    );
  }

  const user = await db.user.findUnique({ where: { id: ctx.user.id } });
  if (!user) {
    return NextResponse.json({ error: "Benutzer nicht gefunden." }, { status: 404 });
  }

  const ok = await verifyPassword(currentPassword, user.passwordHash);
  if (!ok) {
    return NextResponse.json(
      { error: "Das aktuelle Passwort ist falsch." },
      { status: 401 },
    );
  }

  const passwordHash = await hashPassword(newPassword);
  await db.user.update({
    where: { id: user.id },
    data: { passwordHash, mustChangePassword: false },
  });

  return NextResponse.json({
    user: {
      id: user.id,
      name: user.name,
      role: user.role,
      mustChangePassword: false,
    },
  });
}
