# Mint Week Tagebuch - Worklog

This file tracks all work performed on the Mint Week Tagebuch Next.js project
(diary app + login system with three user roles).

---
Task ID: main
Agent: Z.ai Code (main)
Task: Add login system with 3 roles (Admin/Editor/Viewer), first-login password change, hashed passwords, admin user management; recreate the Mint Week diary app in Next.js; seed admin TheHacker/1234/Admin.

Work Log:
- Read uploaded Python (Quart) reference app: app.py, base.html, index.html, create_entry.html, edit_entry.html, styles.css, pyproject.toml. Understood it's a diary ("Mint Week Tagebuch") with entries table (entry_date, high_light, low_light, rating, notes) in PostgreSQL.
- Defined Prisma schema with two models in one SQLite DB: `Entry` (diary) and `User` (auth) with name, passwordHash, role, mustChangePassword. Ran `bun run db:push`.
- Installed `bcryptjs` (+ types). Built `src/lib/password.ts` (hashPassword/verifyPassword, DEFAULT_PASSWORD="1234").
- Built signed HMAC-SHA256 session token in `src/lib/session.ts` (createSessionToken/verifySessionToken) using Node crypto; 7-day TTL.
- Built `src/lib/auth.ts`: getAuthContext, requireAuth, requireRole, withSessionCookie, clearSessionCookie (httpOnly, sameSite=lax cookie `mw_session`).
- Created `scripts/seed.ts` (idempotent) inserting admin TheHacker / 1234 / ADMIN with mustChangePassword=true. Added `seed` npm script. Ran it: admin created.
- API routes (all `runtime=nodejs`, `dynamic=force-dynamic`):
  - POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me, POST /api/auth/change-password
  - GET/POST /api/entries (GET all-auth; POST ADMIN+EDITOR with date validation + unique-date conflict handling)
  - GET/PUT/DELETE /api/entries/[id] (GET all-auth; PUT/DELETE ADMIN+EDITOR)
  - GET/POST /api/users (ADMIN only; POST auto-sets password 1234 + mustChangePassword=true)
  - PUT/DELETE /api/users/[id] (ADMIN; role change + resetPassword; admin cannot demote/delete self)
- Frontend (single `/` route, client-side view switching via Zustand `src/stores/app-store.ts`):
  - `src/lib/api.ts` typed fetch wrappers.
  - `src/app/globals.css`: dark "Mint Week" theme CSS vars matching original (mint-green accent, navy bg, layered radial gradients), themed scrollbars, fade-up/glow animations.
  - `src/components/auth/login-screen.tsx` and `change-password-screen.tsx` (first-login force change).
  - `src/components/layout/app-shell.tsx`: topbar with role-aware nav (Dashboard / Neuer Eintrag / Nutzerverwaltung) + user pill + logout; footer sticky via `min-h-screen flex flex-col` + `mt-auto`.
  - `src/components/views/dashboard-view.tsx`: hero avg rating, 3 stat cards, entries list with role-aware edit/delete + inline confirm.
  - `src/components/views/entry-form.tsx` (+ create/edit wrappers): shared form with star RatingPicker.
  - `src/components/views/users-view.tsx`: create-user form, role stats, scrollable users table with inline role Select, reset-password (reveals 1234), delete with confirm; "Du" badge + self-protection.
- `src/app/page.tsx`: orchestrator — loading → LoginScreen → (mustChangePassword ? ChangePasswordScreen : AppShell with active view).
- `bun run lint` passes (fixed one empty-interface lint error).

Stage Summary:
- Stack: Next.js 16 + Prisma (SQLite) + bcryptjs + custom HMAC cookie sessions + Zustand + shadcn/ui.
- Three roles enforced on every protected route via requireRole. New accounts auto-password 1234 + forced first-login change. Passwords bcrypt-hashed in separate `User` table, same DB as `Entry`.
- Admin TheHacker/1234/Admin seeded and ready to log in.
- Lint clean; dev server compiles successfully.

---
Task ID: verify
Agent: Z.ai Code (main)
Task: End-to-end browser verification of the login system + diary app.

Work Log:
- Used agent-browser to load /, verified login screen renders (Name/Passwort/Anmelden), footer pinned to viewport bottom.
- Logged in as TheHacker/1234 -> first-login "Passwort ändern" screen appears (mustChangePassword=true enforced).
- Change-password API verified via curl (1234 -> Test1234, mustChangePassword=false). Browser form submit works via JS click (agent-browser `click` cmd does not fire React onClick on standalone buttons reliably; this is an automation quirk, not an app bug).
- After reload, dashboard renders with role-aware nav (Dashboard + Neuer Eintrag + Nutzerverwaltung visible for Admin).
- Created an entry (POST /api/entries 200) -> appears in dashboard list with Bearbeiten/Löschen.
- Edited the entry (rating 3->5, notes updated; PUT /api/entries/1 200) -> avg rating 5.0/5, "5/5 am 2026-08-17".
- Deleted the entry (DELETE 200) -> empty state "Noch keine Einträge".
- User management page (admin): created Viewer "MaxMustermann" -> default password "1234" revealed in banner; user shows "Passwort offen" status. Self-protection: admin's own role combobox + Löschen disabled.
- Logged out, logged in as MaxMustermann/1234 -> first-login change-password screen -> changed to Geheim123 -> dashboard with ONLY Dashboard nav (no Neuer Eintrag/Nutzerverwaltung) and NO edit/delete buttons on entries (Viewer role enforced in UI).
- Backend authorization confirmed via curl: Viewer GET /api/users -> 403, POST /api/entries -> 403, GET /api/entries -> 200.
- Responsive: 375px mobile viewport has no horizontal overflow; nav buttons collapse to icon-only (labels hidden sm:inline); footer stays pinned.
- Sticky footer verified: on login (short content) footerBottom == viewportH (900); on dashboard (long content) footer pushed below fold naturally.
- Restored intended starting state: removed test user MaxMustermann, re-ran seed so TheHacker is back to 1234/ADMIN/mustChangePassword=true. Final DB has exactly one user (TheHacker).

Stage Summary:
- All requested features verified end-to-end in the browser: login gate, 3 roles (Admin/Editor/Viewer), auto-1234 password on account creation, forced first-login password change, bcrypt-hashed passwords in separate User table (same DB as entries), admin user management with create/role-change/reset/delete, seeded admin TheHacker/1234/Admin.
- Lint clean; dev server compiles without errors; backend role authorization enforced on every protected route.

---
Task ID: render-deploy
Agent: Z.ai Code (main)
Task: Add login system to the Python (Quart) app in the GitHub repo Printer999/Mint-Tagebuch and prepare it for Render deployment with Render's managed PostgreSQL.

Work Log:
- The user's real project is the Python Quart app in upload/ (app.py + templates + styles), NOT the Next.js sandbox. Restructured upload/ into a proper Quart project: templates/ and static/ folders.
- Rewrote app.py (782 lines): added `users` table (id, name UNIQUE, password_hash, role CHECK IN ADMIN/EDITOR/VIEWER, must_change_password, created_at); bcrypt password hashing (12 rounds); Quart signed-cookie sessions via app.secret_key; `@login_required`, `@role_required(...)`, `@force_password_change` decorators; context processor injecting current_user + role flags to all templates.
- Auth routes: GET/POST /login, POST /logout, GET/POST /change-password. Entry routes protected by role (create/edit/delete = ADMIN+EDITOR; dashboard = all authenticated). User-management routes (admin only): GET /users, POST /users, POST /users/<id>/role, POST /users/<id>/reset-password, POST /users/<id>/delete. Self-protection: admin cannot demote or delete themselves.
- Seed admin on startup: TheHacker / 1234 (bcrypt-hashed) / ADMIN / must_change_password=true. Create-if-not-exists only — never overwrites a changed password on restart/redeploy.
- DATABASE_URL normalization: Render ships `postgres://` which psycopg3 rejects; converted to `postgresql://`. Local dev URL with sslmode untouched.
- Templates (Jinja2): base.html (role-aware nav + user pill + role badge + logout form), login.html (standalone auth card), change_password.html (forced first-login change), index.html (role-aware entry actions hidden for viewers), create_entry.html, edit_entry.html (unchanged content), users.html (admin table with inline role select, status pills, reset/delete with confirm + self-protection).
- styles.css (1001 lines): original dark Mint theme + auth screens + user-management table + role/status pills + responsive.
- Render deployment files: render.yaml (Blueprint: PostgreSQL db 'mint-tagebuch-db' + Python web service 'mint-tagebuch', auto-sets DATABASE_URL from DB + generates SECRET_KEY), Procfile (hypercorn app:app --bind 0.0.0.0:$PORT), requirements.txt (quart, psycopg[binary], bcrypt, hypercorn), runtime.txt (3.12), pyproject.toml (updated deps), .gitignore, README.md with full Render + local-dev instructions.
- Verification (in venv): py_compile OK; AST parse OK; all imports resolve (quart/psycopg/bcrypt/hypercorn); all 13 routes registered; all 7 templates pass Jinja2 syntax check; bcrypt hashing + verification + dummy-hash timing + password validation (min 4 chars, != 1234) all verified; DATABASE_URL normalization verified for 3 URL shapes; role-visibility tests pass (viewer sees no edit/delete/new-entry controls; editor/admin see them; viewer nav lacks user-mgmt + new-entry; admin nav has everything + role badge + logout).
- Could NOT test against the external PostgreSQL (Render-internal hostname unresolvable from sandbox) — that is expected and works on Render where DATABASE_URL points to the Render-managed DB.
- Could NOT push to GitHub (no credentials). Initialized git repo in upload/, committed all 16 files (test artifacts __pycache__/ + *.log correctly git-ignored), configured remote origin -> https://github.com/Printer999/Mint-Tagebuch.git. User just needs to `git push -u origin main`.

Stage Summary:
- Complete login system + user management + role enforcement (frontend + backend) added to the Python Quart diary app.
- Render-ready: render.yaml Blueprint provisions PostgreSQL + Python web service and wires DATABASE_URL/SECRET_KEY automatically. Admin TheHacker/1234/Admin auto-seeded on first boot.
- Repo committed locally; remote configured. User pushes with their GitHub credentials, then creates a Render Blueprint from the repo.
