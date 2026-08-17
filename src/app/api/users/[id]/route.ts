import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { hashPassword, DEFAULT_PASSWORD } from "@/lib/password";
import { requireRole } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function toDTO(u: {
  id: string;
  name: string;
  role: string;
  mustChangePassword: boolean;
  createdAt: Date;
}) {
  return {
    id: u.id,
    name: u.name,
    role: u.role,
    mustChangePassword: u.mustChangePassword,
    createdAt: u.createdAt.toISOString(),
  };
}

const VALID_ROLES = new Set(["ADMIN", "EDITOR", "VIEWER"]);

/**
 * PUT /api/users/[id]
 * Body: { role?: string, resetPassword?: boolean }
 *
 * Updates a user's role and/or resets the password to "1234" (which forces a
 * change on the next login). ADMIN only. The admin cannot demote or delete
 * themselves to avoid locking themselves out.
 */
export async function PUT(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await requireRole(req, ["ADMIN"]);
  if (auth instanceof NextResponse) return auth;

  const { id } = await ctx.params;
  const target = await db.user.findUnique({ where: { id } });
  if (!target) {
    return NextResponse.json({ error: "Benutzer nicht gefunden." }, { status: 404 });
  }

  let body: { role?: unknown; resetPassword?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Ungültige Anfrage." }, { status: 400 });
  }

  const data: { role?: string; passwordHash?: string; mustChangePassword?: boolean } =
    {};

  if (body.role !== undefined) {
    if (typeof body.role !== "string" || !VALID_ROLES.has(body.role)) {
      return NextResponse.json(
        { error: "Ungültige Rolle. Erlaubt: ADMIN, EDITOR, VIEWER." },
        { status: 400 },
      );
    }
    // Prevent the admin from stripping their own admin rights.
    if (target.id === auth.user.id && body.role !== "ADMIN") {
      return NextResponse.json(
        { error: "Du kannst dir nicht selbst die Admin-Rechte entziehen." },
        { status: 400 },
      );
    }
    data.role = body.role;
  }

  if (body.resetPassword === true) {
    data.passwordHash = await hashPassword(DEFAULT_PASSWORD);
    data.mustChangePassword = true;
  }

  if (Object.keys(data).length === 0) {
    return NextResponse.json({ error: "Keine Änderungen übergeben." }, { status: 400 });
  }

  const updated = await db.user.update({ where: { id }, data });
  return NextResponse.json({
    user: toDTO(updated),
    defaultPassword: body.resetPassword === true ? DEFAULT_PASSWORD : undefined,
  });
}

/**
 * DELETE /api/users/[id]
 *
 * Deletes a user. ADMIN only. The admin cannot delete themselves.
 */
export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await requireRole(req, ["ADMIN"]);
  if (auth instanceof NextResponse) return auth;

  const { id } = await ctx.params;
  const target = await db.user.findUnique({ where: { id } });
  if (!target) {
    return NextResponse.json({ error: "Benutzer nicht gefunden." }, { status: 404 });
  }

  if (target.id === auth.user.id) {
    return NextResponse.json(
      { error: "Du kannst dich nicht selbst löschen." },
      { status: 400 },
    );
  }

  await db.user.delete({ where: { id } });
  return NextResponse.json({ ok: true });
}
