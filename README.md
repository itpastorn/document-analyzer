# Document Analyzer

## Syfte

Genomsöker en mapp med dokument (ej rekursivt), analyserar innehållet med hjälp av Claude AI och genererar en Word-rapport samt en Zotero-kompatibel importfil.

## Funktioner

- Stöder PDF, DOCX, TXT, RTF, PowerPoint (PPT, PPTX) och OpenDocument (ODT, ODP, SDW)
- Extraherar författare, redaktörer, titel, år och sammanfattning för varje dokument
- Läser filmetadata (PDF, DOCX, PPTX, EPUB) och skickar den märkt till Claude
  tillsammans med dokumentets början och slut
- Anger aldrig arkivägaren som författare utan belägg i texten eller i
  creator-/Author-metadata (`lastModifiedBy` räknas inte)
- Känner igen AI-genererade dokument och utesluter dem ur Zotero-exporten
- Analyserar om filer vars innehåll har ändrats (SHA-256), även om namnet är detsamma
- Hanterar skiftlägesbyten i filnamn utan dubbla poster
- Registrerar byte-identiska kopior och tomma eller oläsbara filer som åtgärdspunkter
- Genererar en Word-rapport grupperad efter dokumenttyp
- Exporterar en RIS-fil för import till Zotero
- Sparar rapport och logg i en `analyzer`-mapp i den analyserade katalogen
- Loggar processade filer så att körningar inte dubbelarbetar

## Hjälpskript

### Analysera många mappar på en gång

`analyze-all.sh` går rekursivt igenom ett mappträd och kör analysen där den behövs:

```bash
# Från aktuell mapp
./analyze-all.sh

# Angiven mapp, visa bara vad som skulle göras
./analyze-all.sh --folder /sökväg/till/mapp --dry-run
```

Två saker utlöser analys:

1. **En `needs-analysis`-fil i mappen** – mappen analyseras och märkfilen raderas
   efteråt. Misslyckas analysen behålls filen. Ligger `needs-analysis` i en mapp
   som redan har en `analyzer`-undermapp är den ett misstag: den raderas utan att
   analys körs.
2. **Nyare filer än loggen** – finns en `analyzer/processed_files.json` och någon
   fil i mappen är nyare än den, körs analysen om.

### Sortera RIS-filer

Sorterar en RIS-fil efter författare, datum och titel. Skriver resultatet
till `[originalnamn]-sorted.ris` – originalfilen rörs inte.

```bash
# Angiven fil
python "$ANALYZER_HOME/ris-sort.py" mina-referenser.ris

# Enda .ris-filen i aktuell mapp
python "$ANALYZER_HOME/ris-sort.py"
```

Alias-förslag för `.bashrc`:

```bash
alias ris-sort='python "$ANALYZER_HOME/ris-sort.py"'
```

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
- LibreOffice – krävs för SDW och som fallback för ODT/ODP. Ange sökvägen i `config.yaml` under `libreoffice_path`.

## Installation

```bash
git clone https://github.com/itpastorn/document-analyzer.git
cd document-analyzer
python -m venv .venv
source .venv/Scripts/activate  # Windows/Git Bash
pip install -r requirements.txt
```

Skapa en `.env`-fil i projektmappen:

```text
ANTHROPIC_API_KEY=din-nyckel-här
```

## Konfiguration

Redigera `config.yaml` för grundinställningar. Mappar kan anges antingen
i `config.yaml` eller direkt via `--folder`-argumentet vid körning.

- `archive_owner` – arkivägarens namn ('Efternamn, Förnamn'). Används bara för
  att känna igen och spärra hans namn när belägg saknas. Hette tidigare
  `default_author` och fylldes då i som författare för alla okända dokument,
  vilket var orsaken till felaktiga författaruppgifter.
- `anthropic.effort` – tankedjup (`low`, `medium`, `high`). Tomt värde stänger
  av tänkandet.
- `excerpt_head`, `excerpt_tail` – antal tecken från dokumentets början och
  slut som skickas till Claude (standard 9000 och 3000).

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

# Analysera om en enskild fil
python analyzer.py --force stone-james-r-overwhelming-scientific-consensus.pdf

# Rätta äldre poster där arkivägaren angetts som författare
python analyzer.py --recheck-owner

# Se vad som skulle hända, utan API-anrop
python analyzer.py --check

# Kombinera flaggor
python analyzer.py --folder /sökväg/till/mapp --refresh --noris
```

### Flaggor

`--folder` – Anger mapp att analysera, överskriver config.yaml.
`--noris` – Hoppar över skapandet av Zotero RIS-exportfil.
`--refresh` – Raderar loggfilen och analyserar alla filer från scratch.
`--force FIL [FIL ...]` – Analyserar angivna filer på nytt även om de inte ändrats.
`--recheck-owner` – Analyserar om äldre poster (från före schemaversion 2) där
arkivägaren eller ingen alls står som författare.
`--check` – Visar vad som skulle göras (nya, ändrade, trasiga filer,
dubbletter och filer som inte analyseras) utan att anropa Claude eller ändra något.

### Resultaten

Resultaten sparas i en `analyzer`-mapp inuti den analyserade katalogen:

- `analys-[mappnamn].docx` – Word-rapport, med åtgärdspunkter (dubbletter,
  trasiga filer) och en lista över filer som inte analyserats (t.ex. bilder)
- `zotero-import-[mappnamn].ris` – Zotero-importfil
- `processed_files.json` – register över analyserade filer

Vid upprepade körningar analyseras bara nya och ändrade filer, men rapporten
regenereras alltid med allt innehåll.

### Registret (`processed_files.json`)

Nyckeln är filens fullständiga sökväg. Varje post har `role`, `processed`
(tidpunkt) samt `size`, `mtime` och `sha256` för att upptäcka ändringar.

| `role` | Betydelse | Övriga fält |
|---|---|---|
| `primary` | Analyserad fil | `schema_version`, `title`, `author`, `analysis` |
| `secondary` | Samma verk som en primärpost: PDF bredvid EPUB, eller en byte-identisk kopia. Har ingen egen analys – läs primärpostens. | `primary`, `identical_bytes`, och för kopior `duplicate_of` |
| `broken` | Tom eller oläsbar fil | `reason` |

Poster från före schemaversion 2 saknar `role` och `schema_version`: en post med
`analysis` är primär, en med `primary` är sekundär.

`analysis` innehåller:

| Fält | Innehåll |
|---|---|
| `title`, `summary` | Titel och svensk sammanfattning |
| `author` | Upphovsmän, 'Efternamn, Förnamn' separerade med semikolon, eller `null` |
| `editors` | Redaktörer, samma format, eller `null` |
| `author_confidence`, `author_evidence` | `hög`/`medel`/`låg` och var uppgiften står |
| `is_owner_authored` | Arkivägarens egen text |
| `ai_generated`, `ai_signals` | `ja`/`misstänkt`/`nej` och vad som talar för det |
| `type` | artikel, bok, tidskriftsnummer, utdrag, uppsats, avhandling, studie, predikan, föredrag, kursmaterial, dom, myndighetsdokument, anteckningar, AI-rapport, övrigt |
| `year`, `year_source`, `date_full` | År, varifrån det kommer (`text`/`metadata`/`fildatum`/`okänd`) och exakt datum |
| `publication` | Tidskrift, antologi eller serie som dokumentet ingår i |
| `publisher`, `publisher_place`, `isbn`, `pages_total`, `edition` | Bokuppgifter |
| `institution`, `institution_place`, `thesis_type` | Uppsatser och avhandlingar |
| `is_citable` | Citerbar källa |
| `filepath`, `all_filepaths` | Fil som RIS-posten länkar till (PDF om sådan finns) och alla filer i gruppen |

I RIS-exporten blir redaktörer `ED` och författare `AU`. AI-genererade dokument
utesluts, och misstänkt AI-genererade märks med nyckelord och `N1`.

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

## Beroenden

Se `requirements.txt` för fullständig lista (25 paket). Centrala bibliotek:

- [`anthropic`](https://github.com/anthropic/anthropic-sdk-python) – Claude AI-analys
- [`python-docx`](https://python-docx.readthedocs.io/) – Word-rapport
- [`pdfplumber`](https://github.com/jsvine/pdfplumber) – PDF-textextraktion
- [`pyyaml`](https://pyyaml.org/) – konfigurationsfil
- [`python-dotenv`](https://saurabh-kumar.com/python-dotenv/) – `.env`-hantering

Kräver dessutom: Python 3.12+, Anthropic API-nyckel, LibreOffice (för SDW/ODT).

---

## Projektstruktur

```text
document-analyzer/
├── analyzer.py               # Huvudskript för dokumentanalys
├── ris-sort.py               # Sorterar RIS-filer
├── convert-sam-to-docx.py    # Konverterar Ami Pro .SAM till DOCX
├── convert-doc-to-docx.ps1   # Konverterar gamla .DOC till DOCX
├── config.yaml               # Konfiguration inkl. mappar, filformat och LibreOffice-sökväg
├── requirements.txt          # Python-beroenden
├── .env                      # API-nyckel (ignoreras av Git)
└── [analyserad mapp]/
    └── analyzer/             # Skapas automatiskt vid körning
        ├── analys-[mappnamn].docx
        ├── zotero-import-[mappnamn].ris
        └── processed_files.json
```
