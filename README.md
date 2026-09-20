# Mint Week Tagebuch

Persönliches Mint-Woche Tagebuch mit Login-System, drei Benutzerrollen und
Nutzerverwaltung. Geschrieben in Python mit dem Quart-Framework und MySQL.

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

## MySQL einrichten

Voraussetzungen: Python ab 3.12 und ein erreichbarer MySQL-Server.
Das Tabellenschema ist auch mit MySQL 5.5 kompatibel. Rollen und Bewertungen
werden in den Formularrouten geprüft; zusätzliche `CHECK`-Constraints werden
von MySQL erst ab 8.0.16 durchgesetzt.

1. Einmalig eine leere Datenbank auf deinem MySQL-Server anlegen, zum Beispiel
   in MySQL Workbench oder phpMyAdmin:

   ```sql
   CREATE DATABASE mint_tagebuch
       CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
   ```

2. Direkt am Anfang von `app.py` die Standardwerte in diesen Variablen eintragen:

   ```python
   MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
   MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
   MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "mint_tagebuch")
   MYSQL_USER = os.getenv("MYSQL_USER", "root")
   MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
   ```

   Ändere jeweils den zweiten Wert, beispielsweise `""` zu `"dein-passwort"`.
   Host und Port sind getrennt; beim Host keine URL oder `mysql://` eintragen.
   Der Datenbankbenutzer braucht `CREATE`, `REFERENCES`, `SELECT`, `INSERT`,
   `UPDATE` und `DELETE` für diese Datenbank. Die Tabellen `entries`, `users` und
   `user_sessions` erstellt die Anwendung beim Start automatisch.

   Alternativ kannst du gleichnamige Umgebungsvariablen setzen; diese haben
   Vorrang. Für veröffentlichte Deployments die Zugangsdaten darüber setzen,
   damit keine echten Passwörter ins Repository gelangen.

3. Abhängigkeiten installieren und starten:

   ```bash
   uv sync
   uv run python app.py
   ```

   Oder mit einer aktivierten Python-Umgebung und pip:

   ```bash
   pip install -r requirements.txt
   python app.py
   ```

Die App läuft unter http://localhost:5000. Beim ersten Start wird der oben
beschriebene Admin-Account automatisch angelegt.

Für einen Server mit TLS-CA-Zertifikat kannst du zusätzlich `MYSQL_SSL_CA`
am Anfang von `app.py` oder als Umgebungsvariable auf den Zertifikatspfad setzen.
Die Verbindung prüft dann Zertifikat und Servernamen.

Bestehende PostgreSQL-Daten werden durch die Umstellung nicht automatisch
übernommen. Die MySQL-Datenbank startet leer; vorhandene Einträge und Nutzer
müssen bei Bedarf separat übertragen werden. `DATABASE_URL` und die bisherigen
`PG*`-Umgebungsvariablen werden nicht mehr verwendet.

## Deployment auf Render

Die `render.yaml` erstellt den Python-Web-Service. Einen erreichbaren
MySQL-Server mit bereits angelegter Datenbank stellst du separat bereit.

1. Repository auf GitHub aktualisieren und auf Render als **Blueprint** auswählen.
2. Beim Einrichten `MYSQL_HOST`, `MYSQL_DATABASE`, `MYSQL_USER` und
   `MYSQL_PASSWORD` angeben. `MYSQL_PORT` ist standardmäßig `3306`.
3. Falls dein Anbieter ein CA-Zertifikat verlangt, dieses als Secret File
   bereitstellen und `MYSQL_SSL_CA` auf dessen Pfad setzen.
4. Render erzeugt den `SECRET_KEY` für signierte Sessions automatisch.
5. Nach dem Deploy die Render-URL öffnen und mit `TheHacker` / `1234` einloggen.
   Beim ersten Login das Passwort ändern.

Bei einem bestehenden Render-Service die `MYSQL_*`-Variablen vor dem nächsten
Deployment eintragen. Die bisherige PostgreSQL-Datenbank wird von dieser
Anwendung nicht mehr genutzt.

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
├── render.yaml            # Render-Blueprint (Web-Service mit MySQL-Zugangsdaten)
└── README.md
```

## Technische Details

- **Framework:** Quart 0.21 (asynchron, ASGI)
- **Datenbank:** MySQL über PyMySQL, InnoDB und `utf8mb4` für Umlaute und Emojis.
  Zeitstempel werden in UTC gespeichert. Sitzungstokens werden mit Beachtung
  der Groß-/Kleinschreibung verglichen. Nutzernamen sind auf 191 Zeichen begrenzt,
  damit ihr Index auch auf älteren InnoDB-Versionen funktioniert. Die Sortierung
  `utf8mb4_unicode_ci` behandelt Groß-/Kleinschreibung und Akzentvarianten bei der
  Eindeutigkeit gleich; beim Login bleibt die genaue Schreibweise relevant.
- **Passwort-Hashing:** bcrypt (12 Runden Salt)
- **Sessions:** Signierte HttpOnly-Cookies via Quart `session`
- **Rate Limiting:** Pro Client-IP gelten 600 normale Requests pro Minute,
  40 Loginversuche in 5 Minuten sowie 8 Versuche je Nutzerkonto in 15 Minuten.
  Render übergibt dafür die Client-IP über `X-Forwarded-For`; bei einem
  anderen Reverse Proxy muss `TRUST_PROXY_HEADERS=true` bewusst gesetzt werden.
- **Rollen:** `OWNER`, `ADMIN`, `EDITOR`, `VIEWER` als DB-CHECK-Constraint
- **Auth-Decorator:** `@login_required`, `@role_required(...)`, `@force_password_change`

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

Diese Regressionstests prüfen Transaktionen, Fehlerbehandlung und die betroffenen
Routen mit simulierten Datenbankantworten. Sie benötigen keinen MySQL-Server;
eine echte Datenbankverbindung wird damit nicht getestet.

Für einen zusätzlichen Integrationstest mit dem eingetragenen MySQL-Server
unter PowerShell:

```powershell
$env:MINT_TEST_MYSQL = "1"
uv run python -m unittest discover -s tests -v
Remove-Item Env:MINT_TEST_MYSQL
```

Der Integrationstest legt wie ein normaler App-Start die Tabellen und den
Start-Admin an. Zusätzliche Testeinträge und Testnutzer werden innerhalb einer
Transaktion angelegt und anschließend vollständig zurückgerollt.
