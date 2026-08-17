import { NextRequest, NextResponse } from "next/server";
import { db } from "@/lib/db";
import { getAuthContext, requireRole } from "@/lib/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export interface EntryDTO {
  id: number;
  entryDate: string;
  highLight: string;
  lowLight: string;
  rating: number;
  notes: string | null;
  createdAt: string;
}

function toDTO(e: {
  id: number;
  entryDate: string;
  highLight: string;
  lowLight: string;
  rating: number;
  notes: string | null;
  createdAt: Date;
}): EntryDTO {
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
 * GET /api/entries
 *
 * Returns the dashboard summary (counts, averages, best/latest day) and the
 * recent entries. All authenticated users may call this.
 */
export async function GET(req: NextRequest) {
  const ctx = await getAuthContext(req);
  if (!ctx) {
    return NextResponse.json({ error: "Nicht angemeldet." }, { status: 401 });
  }

  const all = await db.entry.findMany({
    orderBy: { entryDate: "desc" },
  });

  const total = all.length;
  const avgRating = total
    ? Math.round((all.reduce((s, e) => s + e.rating, 0) / total) * 10) / 10
    : 0;

  const best = all
    .slice()
    .sort((a, b) => b.rating - a.rating || (a.entryDate < b.entryDate ? 1 : -1))[0];
  const latest = all[0];
  const first = all[all.length - 1];

  const entries = all.slice(0, 8).map(toDTO);

  return NextResponse.json({
    summary: {
      totalEntries: total,
      avgRating,
      firstDate: first?.entryDate ?? null,
      lastDate: latest?.entryDate ?? null,
      bestDay: best
        ? {
            entryDate: best.entryDate,
            highLight: best.highLight,
            rating: best.rating,
          }
        : null,
      latest: latest
        ? { entryDate: latest.entryDate, highLight: latest.highLight }
        : null,
    },
    entries,
    // expose the current role so the frontend can toggle create/edit buttons
    role: ctx.user.role,
  });
}

/**
 * POST /api/entries
 * Body: { entryDate, highLight, lowLight, rating, notes }
 *
 * Creates a new diary entry. Only ADMIN and EDITOR may create entries.
 */
export async function POST(req: NextRequest) {
  const auth = await requireRole(req, ["ADMIN", "EDITOR"]);
  if (auth instanceof NextResponse) return auth;

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

  // Simple ISO date validation.
  if (!/^\d{4}-\d{2}-\d{2}$/.test(entryDate)) {
    return NextResponse.json(
      { error: "Das Datum muss im Format YYYY-MM-DD sein." },
      { status: 400 },
    );
  }

  try {
    const created = await db.entry.create({
      data: { entryDate, highLight, lowLight, rating, notes },
    });
    return NextResponse.json({ entry: toDTO(created) });
  } catch (err) {
    if (
      err &&
      typeof err === "object" &&
      "code" in err &&
      (err as { code?: string }).code === "P2002"
    ) {
      return NextResponse.json(
        { error: "Für dieses Datum existiert bereits ein Eintrag." },
        { status: 409 },
      );
    }
    throw err;
  }
}
