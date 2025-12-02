# Oribasius Collectiones Medicae — Scholarly Database

A collaborative web application for editing, analyzing, and linking ancient Greek medical texts from Oribasius's *Collectiones Medicae*.

## Features

### Browse & Edit
- **Parallel text display**: Greek and English translation side-by-side
- **Full-text search**: Search across Greek text and translations
- **Faceted filtering**: Filter by author, author group, book, medical sect
- **Inline editing**: Rich text editing with edit history tracking
- **Sortable views**: Sort by book/chapter, author, word count, etc.

### Linking
- **CTS URN generation**: Auto-generate URNs following `urn:cts:greekLit:tlg0722.tlg001` scheme
- **External linking**: Link to Perseus Scaife Viewer and other CTS-compliant repositories
- **Custom URN support**: Add your own URN references

### Analytics
- **Word counts**: By author, author group, book, medical sect
- **Comparative analysis**: Compare word counts between any two categories
- **Vocabulary frequency**: Top 100 Greek words with frequency visualization
- **Corpus statistics**: Total words, entries, unique authors

### Data Management
- **CSV import/export**: Full round-trip data portability
- **Edit history**: Track all changes with editor attribution
- **Notes system**: Four note fields per entry for scholarly apparatus

## Demo / Prototype Mode (shareable, no data saved)

To let colleagues explore your current database for free, with edits that *appear* to work but do **not** persist:

1) Ensure your sqlite file (`oribasius.db`) has the data you want to show.  
2) Set env vars when running (app will auto-copy sqlite to a writable `/tmp` if needed):  
   - Optional `DATABASE_URL` for sqlite/postgres. For sqlite, absolute paths work; if the path is read-only (Render source), the app copies the bundled db to `/tmp`.  
   - `DEMO_MODE=true` (commit calls flush for IDs then roll back; nothing is saved)  
3) Start normally (e.g., `gunicorn app:app`). Users can add/edit/delete; after each request, changes are discarded.  

For a quick free share, deploy to Render/Railway with those env vars and upload your sqlite file. Data resets on redeploy. For persistent collaboration, switch to Postgres and set `DEMO_MODE=false`.

## Quick Start

### Local Development

```bash
# Clone and enter directory
cd oribasius-app

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

Visit `http://localhost:5000` in your browser.

### Deploy to Railway (Recommended)

1. Create a [Railway](https://railway.app) account
2. Click "New Project" → "Deploy from GitHub repo"
3. Connect your GitHub and select this repository
4. Railway will auto-detect the configuration and deploy

Your app will be live at `https://your-app.up.railway.app`

### Deploy to Render

1. Create a [Render](https://render.com) account
2. Click "New" → "Web Service"
3. Connect your GitHub repository
4. Render will use `render.yaml` for configuration

## Data Format

Import CSV with these columns (header names flexible):

| Column | Description |
|--------|-------------|
| ID | Unique identifier |
| Author Named | Name as given in text (e.g., "Oribasius") |
| Author | Source author (e.g., "Galen", "Athenaeus") |
| Book | Book number |
| Chapter | Chapter number |
| Title | Greek title |
| Body | Greek text body |
| Translation_Title | English title |
| Translation_content | English translation |
| Location | Citation reference (e.g., "Book 1") |
| Word Count | Greek word count |
| Note, Note2, Note3, Note4 | Scholarly notes |
| Author Group | Classification (e.g., "Galen", "Other") |
| Pneumatist (+Animal) | Medical sect classification |

## URN Scheme

The application generates CTS URNs following this pattern:

```
urn:cts:greekLit:tlg0722.tlg001:{book}.{chapter}
```

- `tlg0722` = Oribasius (TLG author number)
- `tlg001` = Collectiones Medicae
- `{book}.{chapter}` = Passage reference

URNs link to the Perseus Scaife Viewer when available.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/entries` | GET | List entries (with filters) |
| `/api/entries/{id}` | GET | Get single entry |
| `/api/entries` | POST | Create entry |
| `/api/entries/{id}` | PUT | Update entry |
| `/api/entries/{id}` | DELETE | Delete entry |
| `/api/filters` | GET | Get filter options |
| `/api/analytics` | GET | Get corpus analytics |
| `/api/compare` | GET | Compare two categories |
| `/api/history/{id}` | GET | Get edit history |
| `/api/export` | GET | Export CSV |
| `/api/import` | POST | Import CSV |
| `/api/generate-urn/{id}` | POST | Generate URN |

## Tech Stack

- **Backend**: Python/Flask with SQLAlchemy
- **Database**: SQLite (easily upgradeable to PostgreSQL)
- **Frontend**: Vanilla JavaScript with Chart.js for visualizations
- **Fonts**: Cormorant Garamond (Greek), Source Sans 3 (UI), JetBrains Mono (code)
- **Deployment**: Docker-ready with Railway/Render configs

## Future Enhancements

Potential additions for the "Alchemies of Scent" project:

- **Ingredient tagging**: Tag substances, plants, aromatics with structured vocabulary
- **Cross-reference linking**: Link to Galen, Dioscorides, Hippocratic parallels
- **Lemmatized search**: Search across inflected Greek forms
- **Collaborative annotations**: WebAnnotation-compliant annotation layer
- **TEI export**: Generate TEI-XML for long-term preservation
- **Image attachments**: Link to manuscript images

## License

MIT License — adapt freely for your scholarly projects.

## Acknowledgments

Developed for the "Alchemies of Scent" project at the Institute of Philosophy, Czech Academy of Sciences.
