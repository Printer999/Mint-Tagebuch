import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { hashPassword, DEFAULT_PASSWORD } from "@/lib/password";
import { requireRole } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export interface UserDTO {
  id: string;
  name: string;
  role: string;
  mustChangePassword: boolean;
  createdAt: string;
}

function toDTO(u: {
  id: string;
  name: string;
  role: string;
  mustChangePassword: boolean;
  createdAt: Date;
}): UserDTO {
  return {
    id: u.id,
    name: u.name,
    role: u.role,
    mustChangePassword: u.mustChangePassword,
    createdAt: u.createdAt.toISOString(),
  };
}

/**
 * GET /api/users
 *
 * Lists all users. ADMIN only.
 */
export async function GET(req: NextRequest) {
  const auth = await requireRole(req, ["ADMIN"]);
  if (auth instanceof NextResponse) return auth;

  const users = await db.user.findMany({
    orderBy: { createdAt: "asc" },
  });
  return NextResponse.json({ users: users.map(toDTO), currentUserId: auth.user.id });
}

const VALID_ROLES = new Set(["ADMIN", "EDITOR", "VIEWER"]);

/**
 * POST /api/users
 * Body: { name, role }
 *
 * Creates a new user. The password is automatically set to "1234" and the
 * user must change it on first login. ADMIN only.
 */
export async function POST(req: NextRequest) {
  const auth = await requireRole(req, ["ADMIN"]);
  if (auth instanceof NextResponse) return auth;

  let body: { name?: unknown; role?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Ungültige Anfrage." }, { status: 400 });
  }

  const name = typeof body.name === "string" ? body.name.trim() : "";
  const role = typeof body.role === "string" ? body.role : "VIEWER";

  if (!name) {
    return NextResponse.json({ error: "Bitte einen Namen eingeben." }, { status: 400 });
  }
  if (name.length > 40) {
    return NextResponse.json(
      { error: "Der Name darf maximal 40 Zeichen lang sein." },
      { status: 400 },
    );
  }
  if (!VALID_ROLES.has(role)) {
    return NextResponse.json(
      { error: "Ungültige Rolle. Erlaubt: ADMIN, EDITOR, VIEWER." },
      { status: 400 },
    );
  }

  const existing = await db.user.findUnique({ where: { name } });
  if (existing) {
    return NextResponse.json(
      { error: "Ein Benutzer mit diesem Namen existiert bereits." },
      { status: 409 },
    );
  }

  const passwordHash = await hashPassword(DEFAULT_PASSWORD);
  const created = await db.user.create({
    data: {
      name,
      passwordHash,
      role,
      mustChangePassword: true,
    },
  });

  return NextResponse.json({
    user: toDTO(created),
    defaultPassword: DEFAULT_PASSWORD,
  });
}
