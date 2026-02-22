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
## Köra från valfri mapp

Istället för att ange mappar i `config.yaml` kan du köra skriptet direkt
från den mapp du vill analysera. Sätt upp ett alias en gång, sedan räcker
det att skriva `analyze` i terminalen.

### Git Bash (Windows)

Lägg till följande i `~/.bashrc` eller `~/.bash_profile`:
```bash
export ANALYZER_HOME="/c/Users/username/path/to/document-analyzer"
alias analyze='python "$ANALYZER_HOME/analyzer.py" --folder "$(pwd)"'
```

Aktivera direkt utan att starta om terminalen:
```bash
source ~/.bashrc
```

### Terminal (Linux)

Lägg till följande i `~/.bashrc`:
```bash
export ANALYZER_HOME="$HOME/path/to/document-analyzer"
alias analyze='python "$ANALYZER_HOME/analyzer.py" --folder "$(pwd)"'
```

Aktivera:
```bash
source ~/.bashrc
```

### Terminal (Mac)

Lägg till följande i `~/.zshrc`:
```bash
export ANALYZER_HOME="$HOME/path/to/document-analyzer"
alias analyze='python "$ANALYZER_HOME/analyzer.py" --folder "$(pwd)"'
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
cd /path/to/folder
analyze
```

Rapport och Zotero-fil sparas i `output/`-mappen i projektkatalogen,
med mappnamnet inbakat i filnamnet.

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