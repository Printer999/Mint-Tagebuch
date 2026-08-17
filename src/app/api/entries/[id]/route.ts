import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { getAuthContext, requireRole } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function toDTO(e: {
  id: number;
  entryDate: string;
  highLight: string;
  lowLight: string;
  rating: number;
  notes: string | null;
  createdAt: Date;
}) {
  return {
    id: e.id,
    entryDate: e.entryDate,
    highLight: e.highLight,
    lowLight: e.lowLight,
    rating: e.rating,
    notes: e.notes,
    createdAt: e.createdAt.toISOString(),
  };
}

/**
 * GET /api/entries/[id]
 *
 * Returns a single entry. All authenticated users may read entries.
 */
export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await getAuthContext(req);
  if (!auth) {
    return NextResponse.json({ error: "Nicht angemeldet." }, { status: 401 });
  }

  const { id } = await ctx.params;
  const entryId = Number(id);
  if (!Number.isFinite(entryId)) {
    return NextResponse.json({ error: "Ungültige ID." }, { status: 400 });
  }

  const entry = await db.entry.findUnique({ where: { id: entryId } });
  if (!entry) {
    return NextResponse.json({ error: "Eintrag nicht gefunden." }, { status: 404 });
  }
  return NextResponse.json({ entry: toDTO(entry) });
}

/**
 * PUT /api/entries/[id]
 * Body: { entryDate, highLight, lowLight, rating, notes }
 *
 * Updates an entry. Only ADMIN and EDITOR may edit.
 */
export async function PUT(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await requireRole(req, ["ADMIN", "EDITOR"]);
  if (auth instanceof NextResponse) return auth;

  const { id } = await ctx.params;
  const entryId = Number(id);
  if (!Number.isFinite(entryId)) {
    return NextResponse.json({ error: "Ungültige ID." }, { status: 400 });
  }

  let body: {
    entryDate?: unknown;
    highLight?: unknown;
    lowLight?: unknown;
    rating?: unknown;
    notes?: unknown;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Ungültige Anfrage." }, { status: 400 });
  }

  const entryDate =
    typeof body.entryDate === "string" ? body.entryDate.trim() : "";
  const highLight =
    typeof body.highLight === "string" ? body.highLight.trim() : "";
  const lowLight =
    typeof body.lowLight === "string" ? body.lowLight.trim() : "";
  const notes =
    typeof body.notes === "string" && body.notes.trim().length > 0
      ? body.notes.trim()
      : null;
  const ratingNum = Number(body.rating);
  const rating =
    Number.isFinite(ratingNum) && ratingNum >= 1 && ratingNum <= 5
      ? Math.round(ratingNum)
      : 3;

  if (!entryDate || !highLight || !lowLight) {
    return NextResponse.json(
      { error: "Bitte Datum, High und Low Light ausfüllen." },
      { status: 400 },
    );
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(entryDate)) {
    return NextResponse.json(
      { error: "Das Datum muss im Format YYYY-MM-DD sein." },
      { status: 400 },
    );
  }

  const existing = await db.entry.findUnique({ where: { id: entryId } });
  if (!existing) {
    return NextResponse.json({ error: "Eintrag nicht gefunden." }, { status: 404 });
  }

  try {
    const updated = await db.entry.update({
      where: { id: entryId },
      data: { entryDate, highLight, lowLight, rating, notes },
    });
    return NextResponse.json({ entry: toDTO(updated) });
  } catch (err) {
    if (
      err &&
      typeof err === "object" &&
      "code" in err &&
      (err as { code?: string }).code === "P2002"
    ) {
      return NextResponse.json(
        { error: "Dieses Datum ist bereits vergeben. Bitte wähle ein anderes Datum." },
        { status: 409 },
      );
    }
    throw err;
  }
}

/**
 * DELETE /api/entries/[id]
 *
 * Deletes an entry. Only ADMIN and EDITOR may delete.
 */
export async function DELETE(
  req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const auth = await requireRole(req, ["ADMIN", "EDITOR"]);
  if (auth instanceof NextResponse) return auth;

  const { id } = await ctx.params;
  const entryId = Number(id);
  if (!Number.isFinite(entryId)) {
    return NextResponse.json({ error: "Ungültige ID." }, { status: 400 });
  }

  const existing = await db.entry.findUnique({ where: { id: entryId } });
  if (!existing) {
    return NextResponse.json({ error: "Eintrag nicht gefunden." }, { status: 404 });
  }

  await db.entry.delete({ where: { id: entryId } });
  return NextResponse.json({ ok: true });
}
