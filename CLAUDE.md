# Document Analyzer – riktlinjer för Claude

## Om projektet

Python-verktyg som rekursivt analyserar dokumentmappar med Claude AI och genererar Word-rapport samt Zotero-importfil (RIS). Stöder PDF, DOCX, TXT, RTF, PPT/PPTX och OpenDocument-format.

Planerad fortsättning:
1. Fler filtyper
2. Ta hjälp av en VM med äldre Windows för att köra Lotus Word Pro och komma åt mina lwp-filer

## Namnregler för utdatafiler

Alla utdatafiler måste följa dessa normaliseringsregler:

1. Gör om allt till gemener
2. Ersätt mellanslag och understreck med bindestreck
3. Translitterera icke-ASCII-tecken till ASCII-motsvarigheter (t.ex. å→a, ä→a, ö→o, accentbokstäver → basbokstav)
4. Ta bort alla tecken som inte är `a-z`, `0-9` eller `-`
5. Slå ihop flera bindestreck i rad till ett
6. Ta bort inledande och avslutande bindestreck

Använd **aldrig** understreck i filnamn eller projektfilnamn.

## Teknikstack

- Python 3.12+
- `anthropic` SDK – Claude AI-analys
- `python-docx` – Word-rapporter
- `pdfplumber` – PDF-textextraktion
- `pyyaml` – konfiguration (`config.yaml`)
- `python-dotenv` – API-nyckel via `.env`
- LibreOffice – krävs för SDW, fallback för ODT/ODP

## Körmiljö

- Plattform: Windows/Git Bash
- Virtuell miljö: `.venv/Scripts/activate`
- API-nyckel lagras i `.env` (ignoreras av Git)
- Konfiguration i `config.yaml`
