# Mint Week Tagebuch

Persönliches Mint-Woche Tagebuch mit Login-System, drei Benutzerrollen und
Nutzerverwaltung. Geschrieben in Python mit dem Quart-Framework und PostgreSQL.

## Funktionen

### Login-System
- **Login-Seite** am Anfang der Website — ohne Anmeldung ist nichts erreichbar.
- **Drei Rollen:**
  | Rolle | Einträge ansehen | Einträge bearbeiten | Nutzerverwaltung |
  |-------|:---:|:---:|:---:|
  | **Admin** | ✅ | ✅ | ✅ |
  | **Editor** | ✅ | ✅ | ❌ |
  | **Viewer** | ✅ | ❌ | ❌ |
- Beim **ersten Login** wird der Benutzer aufgefordert, sein Passwort zu ändern.
- **Neue Accounts** erhalten automatisch das Passwort `1234` und müssen es beim
  ersten Login ändern.
- Passwörter werden mit **bcrypt** gehasht und in der `users`-Tabelle
  gespeichert — derselben Datenbank wie die Einträge, nur in einer eigenen Tabelle.
- **Nutzerverwaltung** (nur Admin): Accounts anlegen, Rolle ändern, Passwort
  zurücksetzen (auf `1234`), Accounts löschen. Der Admin kann sich nicht selbst
  degradieren oder löschen.

### Start-Admin
Beim ersten Start wird automatisch der Admin-Account angelegt:
```
Name:     TheHacker
Passwort: 1234
Rang:     ADMIN
```
Beim ersten Login wirst du aufgefordert, das Passwort zu ändern.

## Deployment auf Render

Dieses Repository ist so vorbereitet, dass du es nur noch Render übergeben
musst. Die `render.yaml` definiert automatisch alles:

### Schritte
1. **Repository nach GitHub pushen** (falls noch nicht geschehen):
   ```bash
   git init
   git add .
   git commit -m "Login-System + Nutzerverwaltung + Render-Deployment"
   git branch -M main
   git remote add origin https://github.com/Printer999/Mint-Tagebuch.git
   git push -u origin main
   ```

2. Auf [render.com](https://render.com) einloggen → **New** → **Blueprint**.

3. Das GitHub-Repository `Printer999/Mint-Tagebuch` auswählen.

4. Render erkennt die `render.yaml` automatisch und legt an:
   - Eine **PostgreSQL-Datenbank** (`mint-tagebuch-db`, Plan: free)
   - Einen **Python-Web-Service** (`mint-tagebuch`, Plan: free)

5. Render setzt automatisch diese Umgebungsvariablen:
   - `DATABASE_URL` — die Render-PostgreSQL-Verbindungs-URL
   - `SECRET_KEY` — ein zufälliger Wert für signierte Sessions
   - `PYTHON_VERSION` — `3.12.7`

6. Beim ersten Start werden automatisch die Tabellen erstellt und der
   Admin-Account `TheHacker` / `1234` / `ADMIN` angelegt.

7. Nach dem Deploy die Render-URL öffnen und mit `TheHacker` / `1234` einloggen.
   Beim ersten Login Passwort ändern — fertig.

> Der `DATABASE_URL` von Render liefert `postgres://`-Schemata. Die App
> normalisiert das automatisch zu `postgresql://`, damit psycopg3 es akzeptiert.

## Lokale Entwicklung

```bash
# Abhängigkeiten installieren (empfohlen mit uv)
uv sync
# oder mit pip:
pip install -r requirements.txt

# Datenbank-URL setzen (optional, es gibt einen Dev-Default)
export DATABASE_URL="postgresql://user:pass@host:5432/mint_tagebuch?sslmode=require"
export SECRET_KEY="dev-secret"

# Server starten
python app.py
# oder
hypercorn app:app --bind 0.0.0.0:5000
```

Die App läuft unter http://localhost:5000.

## Projektstruktur

```
.
├── app.py                 # Quart-App: Routen, Auth, DB, Rollen
├── templates/
│   ├── base.html          # Layout mit rollenbasierter Navigation + Logout
│   ├── login.html         # Login-Seite
│   ├── change_password.html  # Passwort-Änderung (erzwungen beim ersten Login)
│   ├── index.html         # Dashboard (Einträge + Statistik)
│   ├── create_entry.html # Neuen Eintrag erstellen (Admin/Editor)
│   ├── edit_entry.html    # Eintrag bearbeiten (Admin/Editor)
│   └── users.html         # Nutzerverwaltung (Admin)
├── static/
│   └── styles.css         # Styles ( dunkles Mint-Theme )
├── pyproject.toml         # Projekt-Metadaten (uv)
├── requirements.txt       # Für Render (pip)
├── runtime.txt            # Python-Version
├── Procfile               # Render/Heroku-Start-Kommando
├── render.yaml            # Render-Blueprint (DB + Web-Service)
└── README.md
```

## Technische Details

- **Framework:** Quart 0.21 (asynchron, ASGI)
- **Datenbank:** PostgreSQL (psycopg 3)
- **Passwort-Hashing:** bcrypt (12 Runden Salt)
- **Sessions:** Signierte HttpOnly-Cookies via Quart `session`
- **Rollen:** `ADMIN`, `EDITOR`, `VIEWER` als DB-CHECK-Constraint
- **Auth-Decorator:** `@login_required`, `@role_required(...)`, `@force_password_change`
