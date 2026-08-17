// Typed fetch helpers for the Mint Week backend API.

export interface AuthUser {
  id: string;
  name: string;
  role: "ADMIN" | "EDITOR" | "VIEWER";
  mustChangePassword: boolean;
}

export interface EntryDTO {
  id: number;
  entryDate: string;
  highLight: string;
  lowLight: string;
  rating: number;
  notes: string | null;
  createdAt: string;
}

export interface DashboardSummary {
  totalEntries: number;
  avgRating: number;
  firstDate: string | null;
  lastDate: string | null;
  bestDay: { entryDate: string; highLight: string; rating: number } | null;
  latest: { entryDate: string; highLight: string } | null;
}

export interface DashboardResponse {
  summary: DashboardSummary;
  entries: EntryDTO[];
  role: AuthUser["role"];
}

export interface UserDTO {
  id: string;
  name: string;
  role: AuthUser["role"];
  mustChangePassword: boolean;
  createdAt: string;
}

export interface ApiError {
  error: string;
}

async function request<T>(
  url: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
    credentials: "include",
  });

  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      /* ignore */
    }
  }

  if (!res.ok) {
    const message =
      data && typeof data === "object" && "error" in data
        ? String((data as ApiError).error)
        : `Anfrage fehlgeschlagen (${res.status}).`;
    throw new Error(message);
  }

  return data as T;
}

export const api = {
  me: () => request<{ user: AuthUser | null }>("/api/auth/me"),

  login: (name: string, password: string) =>
    request<{ user: AuthUser }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ name, password }),
    }),

  logout: () =>
    request<{ ok: true }>("/api/auth/logout", { method: "POST" }),

  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ user: AuthUser }>("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ currentPassword, newPassword }),
    }),

  listEntries: () =>
    request<DashboardResponse>("/api/entries"),

  createEntry: (input: {
    entryDate: string;
    highLight: string;
    lowLight: string;
    rating: number;
    notes: string;
  }) =>
    request<{ entry: EntryDTO }>("/api/entries", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  getEntry: (id: number) =>
    request<{ entry: EntryDTO }>(`/api/entries/${id}`),

  updateEntry: (
    id: number,
    input: {
      entryDate: string;
      highLight: string;
      lowLight: string;
      rating: number;
      notes: string;
    },
  ) =>
    request<{ entry: EntryDTO }>(`/api/entries/${id}`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),

  deleteEntry: (id: number) =>
    request<{ ok: true }>(`/api/entries/${id}`, { method: "DELETE" }),

  listUsers: () => request<{ users: UserDTO[]; currentUserId: string }>("/api/users"),

  createUser: (name: string, role: UserDTO["role"]) =>
    request<{ user: UserDTO; defaultPassword: string }>("/api/users", {
      method: "POST",
      body: JSON.stringify({ name, role }),
    }),

  updateUser: (
    id: string,
    input: { role?: UserDTO["role"]; resetPassword?: boolean },
  ) =>
    request<{ user: UserDTO; defaultPassword?: string }>(`/api/users/${id}`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),

  deleteUser: (id: string) =>
    request<{ ok: true }>(`/api/users/${id}`, { method: "DELETE" }),
};
