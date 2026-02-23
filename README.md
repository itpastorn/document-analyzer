# Document Analyzer

En agent som rekursivt genomsöker mappar med dokument, analyserar innehållet
med hjälp av Claude AI och genererar en Word-rapport samt en Zotero-kompatibel
importfil.

## Funktioner

- Stöder PDF, DOCX, TXT, RTF och PowerPoint (PPT, PPTX)
- Extraherar författare, titel, år och sammanfattning för varje dokument
- Hämtar metadata anpassad efter dokumenttyp (artikel, bok, uppsats m.m.)
- Genererar en Word-rapport grupperad efter dokumenttyp
- Exporterar en RIS-fil för import till Zotero
- Sparar rapport och logg i en `analyzer`-mapp i den analyserade katalogen
- Loggar processade filer så att körningar inte dubbelarbetar

## Hjälpskript

### Konvertera Ami Pro (.SAM) till DOCX

Äldre dokument i Ami Pro-format kan konverteras med:
```bash
# En enskild fil
python "$ANALYZER_HOME/convert-sam-to-docx.py" filnamn.SAM

# Alla .SAM-filer i aktuell mapp
python "$ANALYZER_HOME/convert-sam-to-docx.py"

# Alla .SAM-filer i angiven mapp
python "$ANALYZER_HOME/convert-sam-to-docx.py" /sökväg/till/mapp
```

Skriptet hanterar Ami Pro-formateringskoder, svenska tecken (CP 1252),
bevarar filernas ursprungliga tidsstämplar och sparar filnamn i lowercase.

### Konvertera .DOC till DOCX (PowerShell)

Äldre Word-dokument (.DOC) kan konverteras med PowerShell-skriptet
`convert-doc-to-docx.ps1`. Uppdatera `$folderPath` i skriptet och kör
det i PowerShell. Skriptet bevarar ursprungliga tidsstämplar.

Obs: Kräver att Word är installerat. Tillåt automation i Words
Säkerhetscenter under *Inställningar för filblockering* om det behövs.

## Krav

- Python 3.12+
- Anthropic API-nyckel
- LibreOffice (valfritt, för vissa konverteringar)

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

Redigera `config.yaml` för grundinställningar. Mappar kan anges antingen
i `config.yaml` eller direkt via `--folder`-argumentet vid körning.

## Användning
```bash
# Analysera mapp angiven i config.yaml
python analyzer.py

# Analysera specifik mapp
python analyzer.py --folder /sökväg/till/mapp

# Analysera utan att skapa Zotero-fil
python analyzer.py --noris

# Radera logg och analysera allt från scratch
python analyzer.py --refresh

# Kombinera flaggor
python analyzer.py --folder /sökväg/till/mapp --refresh --noris
```

### Flaggor

`--folder` – Anger mapp att analysera, överskriver config.yaml.  
`--noris` – Hoppar över skapandet av Zotero RIS-exportfil.  
`--refresh` – Raderar loggfilen och analyserar alla filer från scratch.

### Resultaten
Resultaten sparas i en `analyzer`-mapp inuti den analyserade katalogen:
- `analys-[mappnamn].docx` – Word-rapport
- `zotero_import_[mappnamn].ris` – Zotero-importfil
- `processed_files.json` – logg över analyserade filer

Vid upprepade körningar analyseras bara nya filer, men rapporten
regenereras alltid med allt innehåll.

## Köra från valfri mapp

Sätt upp ett alias en gång, sedan räcker det att skriva `analyze`
i terminalen från den mapp du vill analysera.

### Git Bash (Windows)

Lägg till följande i `~/.bashrc` eller `~/.bash_profile`:
```bash
export ANALYZER_HOME="/c/Users/username/path/to/document-analyzer"
alias analyze='source "$ANALYZER_HOME/.venv/Scripts/activate" && python "$ANALYZER_HOME/analyzer.py" --folder "$(pwd)"'
```

Aktivera direkt utan att starta om terminalen:
```bash
source ~/.bashrc
```

### Terminal (Linux)

Lägg till följande i `~/.bashrc`:
```bash
export ANALYZER_HOME="$HOME/path/to/document-analyzer"
alias analyze='source "$ANALYZER_HOME/.venv/bin/activate" && python "$ANALYZER_HOME/analyzer.py" --folder "$(pwd)"'
```

Aktivera:
```bash
source ~/.bashrc
```

### Terminal (Mac)

Lägg till följande i `~/.zshrc`:
```bash
export ANALYZER_HOME="$HOME/path/to/document-analyzer"
alias analyze='source "$ANALYZER_HOME/.venv/bin/activate" && python "$ANALYZER_HOME/analyzer.py" --folder "$(pwd)"'
```

Aktivera:
```bash
source ~/.zshrc
```

### PowerShell (Windows)

Öppna din profil med:
```powershell
notepad $PROFILE
```

Lägg till:
```powershell
$env:ANALYZER_HOME = "C:\Users\username\path\to\document-analyzer"
function analyze { python "$env:ANALYZER_HOME\analyzer.py" --folder (Get-Location) }
```

Starta om PowerShell för att aktivera.

### Användning efter uppsättning

Navigera till den mapp du vill analysera och kör:
```bash
cd /sökväg/till/mapp
analyze
```

## Projektstruktur
```
document-analyzer/
├── analyzer.py               # Huvudskript för dokumentanalys
├── convert-sam-to-docx.py    # Konverterar Ami Pro .SAM till DOCX
├── convert-doc-to-docx.ps1   # Konverterar gamla .DOC till DOCX
├── config.yaml               # Konfiguration
├── requirements.txt          # Python-beroenden
├── .env                      # API-nyckel (ignoreras av Git)
└── [analyserad mapp]/
    └── analyzer/             # Skapas automatiskt vid körning
        ├── analys-[mappnamn].docx
        ├── zotero_import_[mappnamn].ris
        └── processed_files.json
```