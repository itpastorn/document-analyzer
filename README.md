# Document Analyzer

En agent som rekursivt genomsöker mappar med dokument, analyserar innehållet
med hjälp av Claude AI och genererar en Word-rapport samt en Zotero-kompatibel
importfil.

## Funktioner

- Stöder PDF, DOCX och TXT - FLER kommer!!!
- Extraherar författare, titel, år och sammanfattning för varje dokument
- Hämtar metadata anpassad efter dokumenttyp (artikel, bok, uppsats m.m.)
- Genererar en Word-rapport grupperad efter dokumenttyp
- Exporterar en RIS-fil för import till Zotero
- Loggar processade filer så att körningar inte dubbelarbetar

## Krav

- Python 3.12+
- Anthropic API-nyckel

## Installation
```bash
git clone https://github.com/itpastorn/document-analyzer.git
cd document-analyzer
python -m venv .venv
source .venv/Scripts/activate  # Windows/Git Bash
pip install -r requirements.txt
```

Skapa en `.env`-fil i projektmappen:
```
ANTHROPIC_API_KEY=din-nyckel-här
```

## Konfiguration

Redigera `config.yaml` och ange de mappar du vill analysera:
Exempel för Windows
```yaml
folders:
  - C:/Users/user/Dropbox/path/to/folder
```

## Användning
```bash
python analyzer.py
```

Resultaten sparas i `output/`-mappen:
- `analys-[mappnamn].docx` – Word-rapport
- `zotero_import_[mappnamn].ris` – Zotero-importfil

Loggfilen `logs/processed_files.json` håller reda på redan analyserade filer.
För att köra om alla filer, ta bort loggfilen:
```bash
rm logs/processed_files.json
```

## Projektstruktur
```
document-analyzer/
├── analyzer.py          # Huvudskript
├── config.yaml          # Konfiguration
├── requirements.txt     # Python-beroenden
├── .env                 # API-nyckel (ignoreras av Git)
├── output/              # Genererade rapporter (ignoreras av Git)
└── logs/                # Loggfiler (ignoreras av Git)
```