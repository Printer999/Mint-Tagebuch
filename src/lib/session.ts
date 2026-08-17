import { createHmac, timingSafeEqual } from "crypto";

export interface SessionUser {
  sub: string; // user id
  name: string;
  role: "ADMIN" | "EDITOR" | "VIEWER";
}

export interface SessionToken {
  sub: string;
  name: string;
  role: string;
  exp: number; // epoch seconds
}

const SESSION_SECRET =
  process.env.SESSION_SECRET ||
  "mint-week-diary-session-secret-change-me-in-production";
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 7; // 7 days

function b64url(input: Buffer | string): string {
  return Buffer.from(input)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function b64urlDecode(input: string): Buffer {
  const padded = input.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  return Buffer.from(padded + pad, "base64");
}

function sign(payload: string): string {
  return createHmac("sha256", SESSION_SECRET).update(payload).digest("base64url");
}

/**
 * Creates a signed session token (header.payload.signature) for the given
 * user. The token is HMAC-SHA256 signed and expires after 7 days.
 */
export function createSessionToken(user: SessionUser): string {
  const payload: SessionToken = {
    sub: user.sub,
    name: user.name,
    role: user.role,
    exp: Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS,
  };
  const payloadB64 = b64url(JSON.stringify(payload));
  const signature = sign(payloadB64);
  return `${payloadB64}.${signature}`;
}

/**
 * Verifies a session token's signature and expiry. Returns the decoded
 * payload or null if the token is invalid/expired.
 */
export async function verifySessionToken(
  token: string,
): Promise<SessionToken | null> {
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const [payloadB64, signature] = parts;

  const expectedSignature = sign(payloadB64);

  try {
    const a = Buffer.from(signature);
    const b = Buffer.from(expectedSignature);
    if (a.length !== b.length || !timingSafeEqual(a, b)) {
      return null;
    }
  } catch {
    return null;
  }

  try {
    const decoded = JSON.parse(b64urlDecode(payloadB64).toString("utf8")) as SessionToken;
    if (typeof decoded.exp !== "number") return null;
    if (decoded.exp < Math.floor(Date.now() / 1000)) return null;
    return decoded;
  } catch {
    return null;
  }
}
