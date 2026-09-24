import copy
import hashlib
import json
import os
import re
import sys
import yaml
import zipfile
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import anthropic
import argparse

# Windows använder cp1252 som stdout-kodning när utdata omdirigeras till fil
# eller pipe – tvinga UTF-8 så att ✓, ✗ och åäö inte kraschar utskrifterna
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Version av analysformatet. Poster med lägre version kan analyseras om med --recheck-owner.
SCHEMA_VERSION = 2

_VALID_NAME = re.compile(r"^[a-zA-Z0-9.\-]+$")

# Kontrollera att alla filer i mappen följer namnreglerna
def validate_filenames(folder):
    invalid = [e.name for e in Path(folder).iterdir() if e.is_file() and not _VALID_NAME.match(e.name)]
    if invalid:
        print(f"⚠️  Följande filer i {folder} följer inte namnreglerna (endast a-zA-Z0-9, bindestreck och punkt tillåts):")
        for name in invalid:
            print(f"   {name}")
        sys.exit(1)

# Ladda API-nyckel från .env
load_dotenv(Path(__file__).parent / ".env")

# Ladda konfiguration
def load_config():
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# Ladda logg över redan processade filer
def load_log(log_path):
    if Path(log_path).exists():
        with open(log_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# Spara logg
def save_log(log_path, log_data):
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Textextraktion
# ---------------------------------------------------------------------------

# Långa PDF:er: läs bara början och slutet – titelsida, copyrightsida och
# eventuella signaturer/copyrightrader på sista sidorna
PDF_HEAD_PAGES = 20
PDF_TAIL_PAGES = 5

# LireOffice-extraktion som fallback för ODT/ODP/SDW eller när odfpy misslyckas
def _libreoffice_extract(filepath, config):
    import subprocess
    import tempfile
    lo_path = config.get("libreoffice_path", "soffice")
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [lo_path, "--headless", "--convert-to", "txt:Text", "--outdir", tmpdir, filepath],
            capture_output=True, text=True, timeout=30
        )
        txt_file = Path(tmpdir) / (Path(filepath).stem + ".txt")
        if txt_file.exists():
            with open(txt_file, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    return None

# Läs textinnehåll från fil
def read_file(filepath, config=None):
    suffix = Path(filepath).suffix.lower()
    try:
        if suffix == ".txt":
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

        elif suffix == ".docx":
            from docx import Document
            doc = Document(filepath)
            texts = [p.text for p in doc.paragraphs]
            for table in doc.tables:
                for row in table.rows:
                    texts.append(" | ".join(cell.text for cell in row.cells))
            return "\n".join(texts)

        elif suffix in (".ppt", ".pptx"):
            from pptx import Presentation
            prs = Presentation(filepath)
            texts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame and shape.text_frame.text.strip():  # type: ignore[union-attr]
                        texts.append(shape.text_frame.text)  # type: ignore[union-attr]
            return "\n".join(texts)

        elif suffix == ".odt":
            try:
                from odf import text, teletype  # type: ignore[import-untyped]
                from odf.opendocument import load as odf_load  # type: ignore[import-untyped]
                doc = odf_load(filepath)
                return teletype.extractText(doc.text)  # type: ignore[union-attr]
            except Exception:
                return _libreoffice_extract(filepath, config)

        elif suffix == ".odp":
            try:
                from odf import draw, teletype  # type: ignore[import-untyped]
                from odf.opendocument import load as odf_load  # type: ignore[import-untyped]
                doc = odf_load(filepath)
                texts = []
                for frame in doc.presentation.getElementsByType(draw.Frame):  # type: ignore[union-attr]
                    texts.append(teletype.extractText(frame))
                return "\n".join(texts)
            except Exception:
                return _libreoffice_extract(filepath, config)

        elif suffix == ".sdw":
            return _libreoffice_extract(filepath, config)

        elif suffix == ".epub":
            try:
                import ebooklib
                from ebooklib import epub
                from bs4 import BeautifulSoup
            except ImportError as exc:
                raise RuntimeError(
                    "Saknade paket för epub: kör '.venv/Scripts/pip install ebooklib beautifulsoup4'"
                ) from exc
            book = epub.read_epub(str(filepath))
            texts = []
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                soup = BeautifulSoup(item.get_content(), "html.parser")
                texts.append(soup.get_text())
            return "\n".join(texts)

        elif suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(filepath)
            n = len(reader.pages)
            if n <= PDF_HEAD_PAGES + PDF_TAIL_PAGES:
                return "\n".join([page.extract_text() or "" for page in reader.pages])
            head = [reader.pages[i].extract_text() or "" for i in range(PDF_HEAD_PAGES)]
            tail = [reader.pages[i].extract_text() or "" for i in range(n - PDF_TAIL_PAGES, n)]
            skipped = n - PDF_HEAD_PAGES - PDF_TAIL_PAGES
            return "\n".join(head + [f"\n[… {skipped} sidor utelämnade …]\n"] + tail)
        else:
            return None
    except Exception as e:
        print(f"  Kunde inte läsa {filepath}: {e}")
        return None

# Skicka början och slut av texten – upphovsuppgifter står ofta sist
# (copyrightrader, signaturer), inte bara på titelsidan
def text_excerpt(content, head=9000, tail=3000):
    if len(content) <= head + tail + 200:
        return content
    skipped = len(content) - head - tail
    return f"{content[:head]}\n\n[… {skipped} tecken utelämnade …]\n\n{content[-tail:]}"


# ---------------------------------------------------------------------------
# Filmetadata
# ---------------------------------------------------------------------------

# Författarvärden som bara är program- eller kontonamn
_JUNK_AUTHORS = {
    "", "user", "admin", "administrator", "owner", "author", "unknown", "okänd",
    "microsoft office user", "windows user", "valued customer", "användare",
}

_AI_TOOL_NAMES = re.compile(
    r"(?:^|-)(chatgpt|gpt|claude|gemini|meta-ai|perplexity|notebooklm|copilot|deepseek|grok)(?:-|$)"
)

# Rensa titelfält. Returnerar (titel, författarledtråd) – ett titelfält som
# börjar med "Author:" innehåller i själva verket en författaruppgift.
def clean_title(value):
    v = str(value or "").strip()
    if not v:
        return None, None
    m = re.match(r"(?i)^author\s*:\s*(.+)$", v)
    if m:
        return None, m.group(1).strip()
    v = re.sub(r"(?i)^microsoft (word|powerpoint|excel)\s*-\s*", "", v)
    v = re.sub(r"(?i)\.(docx?|pdf|pptx?|rtf|txt|odt)$", "", v).strip()
    if re.fullmatch(r"(?i)(untitled|namnlös|title|rubrik|(document|dokument|presentation)\s*\d*)", v):
        return None, None
    return v or None, None

def clean_author(value):
    v = str(value or "").strip()
    return None if v.lower() in _JUNK_AUTHORS else v

# PDF-datum har formen D:20210115120000+01'00'
def _pdf_date(value):
    m = re.match(r"D?:?(\d{4})(\d{2})?(\d{2})?", str(value or ""))
    if not m:
        return None
    return "-".join(g for g in m.groups() if g)

def _docx_app_name(filepath):
    try:
        with zipfile.ZipFile(filepath) as z:
            xml = z.read("docProps/app.xml").decode("utf-8", errors="ignore")
        m = re.search(r"<Application>([^<]*)</Application>", xml)
        return m.group(1).strip() if m else None
    except Exception:
        return None

# Läs filmetadata. Returnerar fält märkta med vad de faktiskt betyder, plus
# förhandssignaler om AI-generering som koden själv kan se.
def read_metadata(filepath):
    suffix = Path(filepath).suffix.lower()
    fields = []
    ai_signals = []

    def add(label, value):
        if value not in (None, ""):
            fields.append((label, str(value).strip()))

    def add_title(label, value):
        title, author_hint = clean_title(value)
        add(label, title)
        if author_hint:
            add(f"{label} (felaktigt titelfält som innehåller en författaruppgift)", author_hint)

    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(filepath)
            md = reader.metadata or {}
            add_title("PDF Title", md.get("/Title"))
            add("PDF Author", clean_author(md.get("/Author")))
            add("PDF Subject", md.get("/Subject"))
            add("PDF Keywords", md.get("/Keywords"))
            add("PDF CreationDate (när filen skapades, osäkert som utgivningsår)", _pdf_date(md.get("/CreationDate")))
            add("PDF Creator (program)", md.get("/Creator"))
            add("PDF Producer (program)", md.get("/Producer"))
            add("Antal sidor", len(reader.pages))

        elif suffix in (".docx", ".pptx"):
            if suffix == ".docx":
                from docx import Document
                doc = Document(filepath)
            else:
                from pptx import Presentation
                doc = Presentation(filepath)
            cp = doc.core_properties
            creator = (cp.author or "").strip()
            add_title("Titelfält", cp.title)
            add("creator (kontot som skapade filen – filhistorik, inte upphovsuppgift)", clean_author(creator))
            add("lastModifiedBy (kontot som sparade senast – aldrig belägg för upphovsman)", clean_author(cp.last_modified_by))
            add("Ämne", cp.subject)
            add("Kategori", cp.category)
            add("Kommentarer", cp.comments)
            add("Nyckelord", cp.keywords)
            add("Skapad", cp.created.date().isoformat() if cp.created else None)
            add("Program", _docx_app_name(filepath))
            if creator.lower() in ("python-docx", "python-pptx", "docx"):
                ai_signals.append(f"filen är maskingenererad (creator={creator})")
            if not creator:
                add("creator", "(tomt)")
            if cp.category and re.search(r"(?i)\bAI\b", cp.category):
                ai_signals.append(f"metadatafältet category = '{cp.category}'")
            if suffix == ".docx":
                hf = []
                for section in doc.sections:
                    for part in (section.header, section.footer):
                        hf.extend(p.text.strip() for p in part.paragraphs if p.text.strip())
                add("Sidhuvud/sidfot", " / ".join(dict.fromkeys(hf))[:500])

        elif suffix == ".epub":
            from ebooklib import epub
            book = epub.read_epub(str(filepath))
            for value, _ in book.get_metadata("DC", "title")[:1]:
                add_title("EPUB title", value)
            for tag in ("creator", "contributor"):
                for value, attrs in book.get_metadata("DC", tag):
                    role = next((v for k, v in (attrs or {}).items() if k.endswith("role")), None)
                    add(f"EPUB {tag}" + (f" (roll: {role})" if role else ""), value)
            for tag in ("date", "publisher", "identifier"):
                for value, _ in book.get_metadata("DC", tag)[:2]:
                    add(f"EPUB {tag}", value)
    except Exception as e:
        add("Metadatafel", str(e))

    if _AI_TOOL_NAMES.search(Path(filepath).stem.lower()):
        ai_signals.append("filnamnet nämner ett AI-verktyg")

    return fields, ai_signals


# ---------------------------------------------------------------------------
# Analys med Claude
# ---------------------------------------------------------------------------

DOC_TYPES = [
    "artikel", "bok", "tidskriftsnummer", "utdrag", "uppsats", "avhandling", "studie",
    "predikan", "föredrag", "kursmaterial", "dom", "myndighetsdokument",
    "anteckningar", "AI-rapport", "övrigt",
]

def _nullable(t):
    return {"type": [t, "null"]}

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "author": _nullable("string"),
        "editors": _nullable("string"),
        "author_confidence": {"type": "string", "enum": ["hög", "medel", "låg"]},
        "author_evidence": _nullable("string"),
        "is_owner_authored": {"type": "boolean"},
        "ai_generated": {"type": "string", "enum": ["ja", "misstänkt", "nej"]},
        "ai_signals": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "type": {"type": "string", "enum": DOC_TYPES},
        "year": _nullable("integer"),
        "year_source": {"type": "string", "enum": ["text", "metadata", "fildatum", "okänd"]},
        "date_full": _nullable("string"),
        "is_citable": {"type": "boolean"},
        "publication": _nullable("string"),
        "publisher": _nullable("string"),
        "publisher_place": _nullable("string"),
        "isbn": _nullable("string"),
        "pages_total": _nullable("integer"),
        "edition": _nullable("string"),
        "institution": _nullable("string"),
        "institution_place": _nullable("string"),
        "thesis_type": _nullable("string"),
    },
    "additionalProperties": False,
}
ANALYSIS_SCHEMA["required"] = list(ANALYSIS_SCHEMA["properties"])

def build_system_prompt(owner):
    return f"""Du katalogiserar dokument i ett personligt forskningsarkiv som tillhör {owner}. För varje dokument får du filnamn, filmetadata och ett textutdrag med dokumentets början och slut. Svara med ett JSON-objekt enligt schemat. Fält som inte går att fastställa sätts till null.

## Upphovsman (author, editors)
- `author` anger bara personer eller organisationer som uttryckligen står som upphovsmän: byline, titelsida, signatur, copyrightrad (t.ex. "Copyright 2021 James R. Stone") eller tillförlitlig bibliografisk metadata. Leta i både början och slutet av utdraget.
- Format: 'Efternamn, Förnamn'. Flera upphovsmän separeras med semikolon. Organisationer skrivs med sitt namn.
- Institutionella upphovsmän räknas: domstolar ("Kammarrätten i Stockholm"), myndigheter, organisationer (Answers in Genesis, Institute for Creation Research, BioLogos, Discovery Institute), tidskrifter.
- Ger en organisation ut materialet utan att någon person anges (plansch, broschyr, text i organisationens egen tidskrift – t.ex. Answers Magazine från Answers in Genesis), är organisationen upphovsman.
- Redaktörer ("edited by", "ed.", "eds.", "red.", "Herausgegeben von") läggs i `editors`, aldrig i `author`. En antologi eller redigerad volym har normalt `author: null`. EPUB-metadatans creator är ofta redaktören för antologier; väg den mot titelsidan.
- Ett tidskriftsnummer eller temanummer får typen tidskriftsnummer, tidskriften i `publication` och inga bidragsgivare i `author`.
- Finns inget belägg: `author: null` och `author_confidence: "låg"`. Gissa aldrig. Ett tomt fält är bättre än ett felaktigt namn.
- `author_evidence`: kort beskrivning av var uppgiften står (t.ex. "copyrightrad sist i texten", "PDF Author", "titelsidan").

## Arkivägaren
Arkivet tillhör {owner}, men de flesta dokumenten i det är skrivna av andra. Att en fil ligger här säger ingenting om vem som skrev den.
- Ange {owner} som författare bara om hans namn står i texten som upphovsman, eller om texten tydligt är hans egna anteckningar, utkast, granskningar eller kommentarer (vanligen på svenska och personligt hållna, utan någon annan upphovsman) och filmetadatas creator dessutom är han.
- En samling citat som han har ordnat med egna rubriker, kommentarer eller inskott (t.ex. "[… sic!]") räknas som hans anteckningar när creator är han och ingen annan sammanställare anges.
- `lastModifiedBy` betyder bara att han har sparat filen och är aldrig belägg för upphovsmannaskap.
- `is_owner_authored` är true bara vid sådana starka signaler, annars false.

## Filmetadata
Metadata är filhistorik, inte upphovsuppgifter. I docx är creator kontot som skapade filen (ofta den som skrev av, översatte eller konverterade texten). PDF Author och EPUB creator stämmer ofta men inte alltid, och fält kan vara förväxlade. Väg metadata mot texten; texten väger tyngst.

## Årtal (year, year_source)
Prioritetsordning:
1. Uttryckligt publicerings-, copyright- eller dateringsår i dokumentets egen text → `year_source: "text"`.
2. Bibliografisk metadata (EPUB date, ISBN-/tryckortssida) → `"metadata"`.
3. PDF CreationDate eller filens skapandedatum → `"fildatum"`.
4. Annars `year: null`, `year_source: "okänd"`.
Årtal i citerade källor, referenser eller omtalade händelser får aldrig bli dokumentets eget årtal.

## AI-genererade dokument (ai_generated, ai_signals)
Signaler att väga in:
- docx creator är python-docx, docx, tom eller ett verktygsnamn.
- Filnamnet nämner ett AI-verktyg (chatgpt, claude, gemini, perplexity, notebooklm, copilot).
- Texten beskriver sig själv som en rapport ("Rapporten sammanställer …") med typisk rubrikstruktur ("Omfattning och metod", "Vad som fattas i rapporten").
- AI-verktyg nämns som upphov, eller dokumentet deklarerar själv att det är AI-genererat (i ingress, sidfot eller metadata).
- Du-tilltal riktat till beställaren, diagnos- och rekommendationsformat ("Kortversionen: Ditt argument …").
Sätt "ja" vid tydliga belägg, "misstänkt" vid indicier och "nej" annars. Lista signalerna i `ai_signals`. Ett AI-genererat dokument får typen AI-rapport, `is_owner_authored: false`, `is_citable: false` och `author: null`, om inte en namngiven människa uttryckligen står som författare.

## Typer (type)
- artikel: text publicerad i tidskrift, tidning, på webbplats eller i antologi.
- bok: monografi eller redigerad volym, även äldre böcker utan ISBN.
- tidskriftsnummer: ett helt nummer eller temanummer av en tidskrift.
- utdrag: en del av ett större verk, t.ex. innehållsförteckning, enstaka kapitel, provsidor eller register.
- uppsats: studentuppsats (kandidat-, magister-, masteruppsats).
- avhandling: doktors- eller licentiatavhandling.
- studie: utredning eller forskningsrapport av en namngiven person eller organisation.
- predikan: predikan eller andakt för en församling.
- föredrag: det som sades muntligt vid en föreläsning, ett föredrag, en intervju eller ett panelsamtal – transkript, undertexter (t.ex. från YouTube) eller utskrift.
- kursmaterial: skriftligt material som en lärare ger ut till en kurs: kursguider (t.ex. The Great Courses), class notes, föreläsningsanteckningar, handouts och studiehandledningar. Sådant är kursmaterial, inte föredrag.
- dom: domstolsavgörande.
- myndighetsdokument: beslut, utredning eller annan handling från en myndighet, som inte är en dom.
- anteckningar: arbetsanteckningar, utkast, granskningar och kommentarer som inte är färdiga publikationer.
- AI-rapport: se ovan.
- övrigt: allt annat (planscher, affischer, brev, listor).

## Övrigt
- `summary`: sammanfattning på svenska, 30–150 ord beroende på innehållets komplexitet.
- `is_citable`: true om dokumentet är en källa som går att citera i akademiskt arbete.
- `publication`: tidskrift, antologi eller serie som dokumentet ingår i.
- `date_full`: exakt datum i formatet YYYY-MM-DD, bara om det står i texten.
- `publisher`, `publisher_place`, `isbn`, `pages_total`, `edition`: främst för böcker.
- `institution`, `institution_place`, `thesis_type`: bara för uppsatser och avhandlingar."""

def build_user_prompt(filepath, excerpt, metadata_fields, ai_signals):
    meta_lines = "\n".join(f"- {label}: {value}" for label, value in metadata_fields) or "- (ingen metadata)"
    signal_lines = "\n".join(f"- {s}" for s in ai_signals) or "- (inga)"
    return f"""Filnamn: {Path(filepath).name}

Filmetadata:
{meta_lines}

Tekniska signaler om AI-generering som koden har hittat:
{signal_lines}

Dokumentets text (början och slut, kan vara avkortad):
<document>
{excerpt}
</document>"""

# Jämför personnamn oavsett ordning och skiljetecken ("Gunther, Lars" = "Lars Gunther")
def _name_tokens(name):
    return frozenset(re.findall(r"\w+", (name or "").casefold()))

def split_names(value):
    return [a.strip() for a in (value or "").split(";") if a.strip()]

def is_unknown_author(value):
    return (value or "").strip().lower() in ("", "okänd", "unknown", "null", "none")

# Står arkivägarens namn i texten, eller i metadata som anger upphovsman eller
# skapare? lastModifiedBy räknas inte.
def has_owner_evidence(owner, text, metadata_fields):
    owner_tokens = _name_tokens(owner)
    if not owner_tokens:
        return False
    if owner_tokens <= _name_tokens(text):
        return True
    return any(
        label.startswith(("creator", "PDF Author", "EPUB creator")) and _name_tokens(value) == owner_tokens
        for label, value in metadata_fields
    )

# Kodens skyddsnät efter modellens svar – framför allt mot att arkivägaren
# anges som författare utan belägg
def apply_guards(result, owner, ai_signals, owner_evidence):
    if is_unknown_author(result.get("author")):
        result["author"] = None
    if is_unknown_author(result.get("editors")):
        result["editors"] = None

    if ai_signals and result.get("ai_generated") == "nej":
        result["ai_generated"] = "misstänkt"
        result["ai_signals"] = (result.get("ai_signals") or []) + ai_signals

    if result.get("ai_generated") == "ja":
        result["is_owner_authored"] = False
        result["type"] = "AI-rapport"
        result["is_citable"] = False

    # Utan namnet i texten eller i creator/Author-metadata kan arkivägaren inte vara upphovsman
    if not owner_evidence:
        result["is_owner_authored"] = False

    owner_tokens = _name_tokens(owner)
    if owner_tokens and not result.get("is_owner_authored"):
        authors = split_names(result.get("author"))
        kept = [a for a in authors if _name_tokens(a) != owner_tokens]
        if len(kept) != len(authors):
            result["author"] = "; ".join(kept) or None
            if not kept:
                result["author_confidence"] = "låg"
    return result

def analyze_document(client, config, filepath, content, owner):
    anthropic_cfg = config["anthropic"]
    metadata_fields, ai_signals = read_metadata(filepath)
    excerpt = text_excerpt(
        content,
        head=config.get("excerpt_head", 9000),
        tail=config.get("excerpt_tail", 3000),
    )
    output_config = {"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}}
    effort = anthropic_cfg.get("effort")
    if effort:
        output_config["effort"] = effort
    message = client.messages.create(
        model=anthropic_cfg["model"],
        max_tokens=anthropic_cfg["max_tokens"],
        thinking={"type": "adaptive"} if effort else {"type": "disabled"},
        system=[{
            "type": "text",
            "text": build_system_prompt(owner),
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": build_user_prompt(filepath, excerpt, metadata_fields, ai_signals)}],
        output_config=output_config,  # type: ignore[arg-type]
    )
    if message.stop_reason == "refusal":
        raise ValueError("Claude avböjde att analysera dokumentet")
    if message.stop_reason == "max_tokens":
        raise ValueError("Svaret klipptes av – öka max_tokens i config.yaml")
    # Svaret kan innehålla flera block (t.ex. thinking) – plocka texten
    raw = "".join(b.text for b in message.content if b.type == "text").strip()
    if not raw:
        raise ValueError(f"Claude returnerade ingen text (stop_reason: {message.stop_reason})")
    result = json.loads(raw)
    return apply_guards(result, owner, ai_signals, has_owner_evidence(owner, excerpt, metadata_fields))


# ---------------------------------------------------------------------------
# Registret (processed_files.json)
# ---------------------------------------------------------------------------
#
# Nyckel: filens fullständiga sökväg. Varje post har en roll:
#   primary   – analyserad fil; "analysis" innehåller resultatet och
#               "all_filepaths" alla filer som hör till samma verk
#   secondary – samma verk som "primary" (t.ex. PDF bredvid EPUB, eller en
#               byte-identisk kopia). "identical_bytes" anger vilket.
#   broken    – tom eller oläsbar fil; "reason" anger varför
# Alla poster har "size", "mtime" och "sha256" för att upptäcka ändringar.

def entry_role(entry):
    if "role" in entry:
        return entry["role"]
    if "analysis" in entry:
        return "primary"
    if "primary" in entry:
        return "secondary"
    return "broken"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def fingerprint(path):
    st = Path(path).stat()
    return {"size": st.st_size, "mtime": st.st_mtime, "sha256": sha256_file(path)}

def registry_index(log):
    return {os.path.normcase(k): k for k in log}

# Byt nyckel och alla referenser till den
def _rename_key(log, old, new):
    for entry in log.values():
        for field in ("primary", "duplicate_of"):
            if entry.get(field) == old:
                entry[field] = new
        analysis = entry.get("analysis")
        if analysis:
            if analysis.get("filepath") == old:
                analysis["filepath"] = new
            if old in (analysis.get("all_filepaths") or []):
                analysis["all_filepaths"] = [new if p == old else p for p in analysis["all_filepaths"]]

# Ta bort en primärpost med alla filer i gruppen och alla kopior som pekar på den.
# Returnerar de borttagna sökvägarna.
def drop_group(log, key):
    entry = log.get(key)
    if entry is None:
        return []
    if entry_role(entry) == "secondary" and entry.get("primary") in log:
        return drop_group(log, entry["primary"])
    paths = {key}
    if entry_role(entry) == "primary":
        paths.update(entry["analysis"].get("all_filepaths") or [])
    paths.update(k for k, v in log.items() if v.get("primary") == key)
    for p in paths:
        log.pop(p, None)
    return sorted(paths)

# Koppla loss en sekundär fil från sin primärpost
def detach_secondary(log, key):
    entry = log.pop(key, None)
    primary = log.get((entry or {}).get("primary"))
    if not primary or "analysis" not in primary:
        return
    analysis = primary["analysis"]
    remaining = [p for p in (analysis.get("all_filepaths") or []) if p != key]
    analysis["all_filepaths"] = remaining
    if analysis.get("filepath") == key:
        pdf_paths = [p for p in remaining if Path(p).suffix.lower() == ".pdf"]
        analysis["filepath"] = pdf_paths[0] if pdf_paths else entry["primary"]

# Rätta nycklar efter skiftlägesbyten och ta bort poster för filer som inte finns.
# Windows skiljer inte på versaler och gemener, så Path.exists() räcker inte –
# filnamnet jämförs mot den faktiska katalogposten.
def reconcile_registry(log):
    dir_cache = {}

    def actual_path(key):
        p = Path(key)
        d = p.parent
        if d not in dir_cache:
            dir_cache[d] = {e.name.lower(): e.name for e in d.iterdir()} if d.is_dir() else {}
        name = dir_cache[d].get(p.name.lower())
        return str(d / name) if name else None

    for key in list(log):
        if key not in log:
            continue
        actual = actual_path(key)
        if actual is None:
            role = entry_role(log[key])
            if role == "primary":
                removed = drop_group(log, key)
                print(f"  Borttagen (saknas): {' + '.join(Path(p).name for p in removed)}")
            elif role == "secondary":
                detach_secondary(log, key)
                print(f"  Borttagen (saknas): {Path(key).name}")
            else:
                del log[key]
        elif actual != key:
            entry = log.pop(key)
            if actual in log:
                # Skiftlägesdubblett: behåll den senast analyserade posten
                if entry.get("processed", "") > log[actual].get("processed", ""):
                    log[actual] = entry
                print(f"  Skiftlägesdubblett borttagen: {Path(key).name} (behåller {Path(actual).name})")
            else:
                log[actual] = entry
                print(f"  Nytt skiftläge i filnamn: {Path(key).name} → {Path(actual).name}")
            _rename_key(log, key, actual)
    return log

# Hitta filer vars innehåll har ändrats sedan analysen. Storlek och mtime
# jämförs först; hashen räknas bara om de skiljer sig. Äldre poster utan
# fingeravtryck får ett i efterhand utan att analyseras om.
def detect_changes(log):
    changed = []
    backfilled = 0
    for key, entry in log.items():
        p = Path(key)
        if not p.exists():
            continue
        st = p.stat()
        if entry.get("sha256") and entry.get("size") == st.st_size and entry.get("mtime") == st.st_mtime:
            continue
        digest = sha256_file(p)
        if entry.get("sha256") in (None, digest):
            if entry.get("sha256") is None:
                backfilled += 1
            entry.update({"size": st.st_size, "mtime": st.st_mtime, "sha256": digest})
            continue
        changed.append(key)
    return changed, backfilled

# Ta bort ändrade filer ur registret så att de analyseras om
def forget_changed(log, changed):
    for key in changed:
        if key not in log:
            continue
        role = entry_role(log[key])
        if role == "primary":
            drop_group(log, key)
        elif role == "secondary":
            detach_secondary(log, key)
        else:
            del log[key]
        print(f"  Ändrad sedan analysen: {Path(key).name}")

# Filformat sorterade efter prioritet vid val av analyskälla
_ANALYSIS_PRIORITY = {".epub": 0, ".pdf": 1}

# Filer som inte är dokument och inte behöver nämnas i rapporten
_IGNORED_FILES = {"contents.md", "needs-analysis", "desktop.ini", "thumbs.db", ".dropbox"}

# Hitta alla filer att processa, grupperade per stam (t.ex. bok.epub + bok.pdf = en grupp).
# Returnerar (nya grupper, tillägg). Nya grupper är listor av sökvägar sorterade efter
# prioritet. Tillägg är (primärnyckel, [nya filer]) för filer som dykt upp bredvid ett
# redan analyserat verk.
def find_files(folders, extensions, log):
    from collections import defaultdict
    index = registry_index(log)
    groups = []
    additions = []
    for folder in folders:
        by_stem = defaultdict(list)
        for entry in Path(folder).iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in extensions:
                continue
            by_stem[entry.stem.lower()].append(entry)

        for _stem, entries in by_stem.items():
            entries.sort(key=lambda e: (_ANALYSIS_PRIORITY.get(e.suffix.lower(), 99), e.name))
            group = [str(e) for e in entries]
            logged = [index[os.path.normcase(p)] for p in group if os.path.normcase(p) in index]
            new = [p for p in group if os.path.normcase(p) not in index]
            if not new:
                continue
            primaries = {k if entry_role(log[k]) == "primary" else log[k].get("primary") for k in logged}
            primaries = [k for k in primaries if k in log and entry_role(log[k]) == "primary"]
            if primaries:
                additions.append((primaries[0], new))
                continue
            # Övriga registrerade filer i gruppen (t.ex. trasiga) analyseras om tillsammans med de nya
            for k in logged:
                log.pop(k, None)
            groups.append(group)
    return groups, additions

def unanalyzed_files(folder, extensions):
    return sorted(
        e.name for e in Path(folder).iterdir()
        if e.is_file()
        and e.suffix.lower() not in extensions
        and e.name.lower() not in _IGNORED_FILES
        and not e.name.startswith(".")
    )


# ---------------------------------------------------------------------------
# Rapporter
# ---------------------------------------------------------------------------

# Kontrollera om filen är låst (öppen i annat program)
def check_file_locked(filepath):
    try:
        with open(filepath, "a"):
            pass
        return False
    except IOError:
        return True

def _gray(paragraph):
    from docx.shared import Pt, RGBColor
    paragraph.runs[0].font.size = Pt(9)
    paragraph.runs[0].font.color.rgb = RGBColor(128, 128, 128)

# Generera Word-rapport
def generate_word_report(results, output_path, folder_name="", duplicates=(), broken=(), unanalyzed=()):
    from docx import Document as DocxDocument
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if check_file_locked(output_path):
        print(f"\n⚠️  Kan inte spara rapporten – filen är öppen i Word:")
        print(f"   {output_path}")
        print(f"   Stäng filen och tryck Enter för att försöka igen...")
        input()
    doc = DocxDocument()

    # Titel
    title = doc.add_heading(f"Analys av innehåll i mappen {folder_name}", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Datum
    date_para = doc.add_paragraph(f"Genererad: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # Sammanfattning
    doc.add_heading(f"Totalt analyserade dokument: {len(results)}", level=2)
    doc.add_paragraph()

    # Åtgärdspunkter
    if duplicates or broken:
        doc.add_heading("Åtgärdspunkter", level=1)
        for dup, primary in duplicates:
            doc.add_paragraph(
                f"Byte-identisk dubblett: {Path(dup).name} är samma fil som {Path(primary).name}",
                style="List Bullet",
            )
        for path, reason in broken:
            doc.add_paragraph(f"Trasig fil: {Path(path).name} – {reason}", style="List Bullet")
        doc.add_paragraph()

    # Gruppera efter typ
    by_type = {}
    for r in results:
        t = r.get("type", "övrigt")
        by_type.setdefault(t, []).append(r)

    for doc_type, items in sorted(by_type.items()):
        doc.add_heading(doc_type[:1].upper() + doc_type[1:], level=1)
        for item in items:
            # Rubrik
            doc.add_heading(item.get("title", "Utan titel"), level=2)

            # Författare, redaktörer och år/datum
            date_str = item.get("date_full") or item.get("year") or "okänt"
            parts = [f"Författare: {item.get('author') or 'Okänd'}"]
            if item.get("editors"):
                parts.append(f"Redaktörer: {item['editors']}")
            parts.append(f"År: {date_str}")
            p = doc.add_paragraph("  |  ".join(parts))
            p.runs[0].italic = True

            # Artikel, utdrag eller tidskriftsnummer: publikation
            if item.get("publication") and item.get("type") in ("artikel", "utdrag", "tidskriftsnummer"):
                pub = doc.add_paragraph(f"Publikation: {item['publication']}")
                pub.runs[0].italic = True

            # Uppsatsspecifikt: lärosäte
            if item.get("type") in ("uppsats", "avhandling") and item.get("institution"):
                inst_str = item["institution"]
                if item.get("institution_place"):
                    inst_str += f", {item['institution_place']}"
                if item.get("thesis_type"):
                    inst_str += f" ({item['thesis_type']})"
                ins = doc.add_paragraph(f"Lärosäte: {inst_str}")
                ins.runs[0].italic = True

            # AI-generering och arkivägarens egna texter
            if item.get("ai_generated") in ("ja", "misstänkt"):
                signals = "; ".join(item.get("ai_signals") or [])
                label = "AI-genererad" if item["ai_generated"] == "ja" else "Misstänkt AI-genererad"
                ai = doc.add_paragraph(f"{label}" + (f" ({signals})" if signals else ""))
                ai.runs[0].bold = True
            if item.get("is_owner_authored"):
                own = doc.add_paragraph("Arkivägarens egen text")
                _gray(own)

            # Filnamn – visa alla filer om flera ingår i gruppen
            all_paths = item.get("all_filepaths") or [item.get("filepath", "")]
            fn_label = "Filer" if len(all_paths) > 1 else "Fil"
            fn_names = " + ".join(Path(p).name for p in all_paths)
            _gray(doc.add_paragraph(f"{fn_label}: {fn_names}"))

            # Undermapp (om filen inte ligger direkt i rotmappen)
            file_folder = Path(item['filepath']).parent.name
            if file_folder != folder_name:
                _gray(doc.add_paragraph(f"Mapp: {file_folder}"))

            # Sammanfattning
            doc.add_paragraph(item.get("summary", ""))
            doc.add_paragraph()

    # Filer som inte analyserats (bilder m.m.)
    if unanalyzed:
        doc.add_heading("Filer som inte analyserats", level=1)
        doc.add_paragraph("Filtyper som verktyget inte läser. De ingår i mappen men inte i analysen ovan.")
        for name in unanalyzed:
            doc.add_paragraph(name, style="List Bullet")

    doc.save(output_path)
    print(f"Word-rapport sparad: {output_path}")

# Formatera författarnamn för RIS (efternamn, förnamn)
def format_ris_author(name):
    name = name.strip()
    if "," in name:
        return name
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[-1]}, {' '.join(parts[:-1])}"
    return name

# Omvandla filväg till file:/// URI
# Används för att skapa länkar till bilagor i Zotero-rapporten
def filepath_to_uri(filepath):
    # Omvandla Windows-sökväg till file:/// URI
    path = Path(filepath).resolve()
    # Ersätt bakåtsnedstreck med framåtsnedstreck
    uri = path.as_uri()
    return uri

# Generera Zotero RIS-export
def generate_zotero_export(results, output_path):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    NON_CITABLE_TYPES = {"predikan", "övrigt", "anteckningar", "AI-rapport"}
    NON_CITABLE_EXTENSIONS = {".ppt", ".pptx"}

    # AI-genererade dokument är inga källor och utesluts helt
    citable = [
        r for r in results
        if r.get("is_citable")
        and r.get("type") not in NON_CITABLE_TYPES
        and r.get("ai_generated") != "ja"
        and Path(r.get("filepath", "")).suffix.lower() not in NON_CITABLE_EXTENSIONS
    ]

    type_map = {
        "artikel": "JOUR",
        "uppsats": "THES",
        "avhandling": "THES",
        "bok": "BOOK",
        "studie": "RPRT",
        "tidskriftsnummer": "JFULL",
        "utdrag": "CHAP",
        "föredrag": "SLIDE",
        "dom": "CASE",
        "myndighetsdokument": "GOVDOC",
    }

    lines = []
    for item in citable:
        ris_type = type_map.get(item.get("type", ""), "GEN")
        authors = [a for a in split_names(item.get("author")) if not is_unknown_author(a)]
        editors = split_names(item.get("editors"))
        if ris_type == "BOOK" and editors and not authors:
            ris_type = "EDBOOK"
        lines.append(f"TY  - {ris_type}")
        lines.append(f"TI  - {item.get('title', 'Utan titel')}")
        if item.get("filepath"):
            lines.append(f"L1  - {filepath_to_uri(item['filepath'])}")

        for a in authors:
            lines.append(f"AU  - {format_ris_author(a)}")
        for e in editors:
            lines.append(f"ED  - {format_ris_author(e)}")

        # Datum
        if item.get("date_full"):
            lines.append(f"DA  - {item['date_full']}")
        elif item.get("year"):
            lines.append(f"PY  - {item['year']}")

        # Sammanfattning
        if item.get("summary"):
            lines.append(f"N2  - {item['summary']}")

        # Misstänkt AI-generering märks så att den syns i Zotero
        if item.get("ai_generated") == "misstänkt":
            lines.append("KW  - misstänkt AI-genererad")
            signals = "; ".join(item.get("ai_signals") or [])
            lines.append(f"N1  - Misstänkt AI-genererad" + (f": {signals}" if signals else ""))

        # Publikation: tidskrift för artiklar, annars överordnat verk eller serie
        if item.get("publication"):
            tag = "JO" if ris_type in ("JOUR", "JFULL") else "T2"
            lines.append(f"{tag}  - {item['publication']}")

        # Bokspecifikt
        if item.get("publisher"):
            lines.append(f"PB  - {item['publisher']}")
        if item.get("publisher_place"):
            lines.append(f"CY  - {item['publisher_place']}")
        if item.get("isbn"):
            lines.append(f"SN  - {item['isbn']}")
        if item.get("pages_total"):
            lines.append(f"SP  - {item['pages_total']} sidor")
        if item.get("edition"):
            lines.append(f"ET  - {item['edition']}")

        # Uppsatsspecifikt
        if item.get("institution"):
            lines.append(f"PB  - {item['institution']}")
        if item.get("institution_place"):
            lines.append(f"CY  - {item['institution_place']}")
        if item.get("thesis_type"):
            lines.append(f"M3  - {item['thesis_type']}")

        lines.append("ER  - ")
        lines.append("")

    if not citable:
        print("Inga citeringsbara poster – RIS-fil skapas inte.")
        return

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Zotero RIS-fil sparad: {output_path} ({len(citable)} poster)")


# ---------------------------------------------------------------------------
# Huvudprogram
# ---------------------------------------------------------------------------

# Hitta registerposter som motsvarar filnamn angivna med --force
def resolve_forced(log, names, folder):
    index = registry_index(log)
    by_name = {}
    for k in log:
        by_name.setdefault(Path(k).name.lower(), []).append(k)
    keys = []
    for name in names:
        candidate = os.path.normcase(str(Path(folder) / name))
        if candidate in index:
            keys.append(index[candidate])
        elif Path(name).name.lower() in by_name:
            keys.extend(by_name[Path(name).name.lower()])
        else:
            print(f"  ⚠️  --force: {name} finns inte i registret (analyseras ändå om den är ny)")
    return keys

# Poster från före SCHEMA_VERSION 2 där arkivägaren eller ingen alls står som författare
def owner_suspects(log, owner):
    owner_tokens = _name_tokens(owner)
    suspects = []
    for k, v in log.items():
        if entry_role(v) != "primary" or v.get("schema_version", 1) >= SCHEMA_VERSION:
            continue
        authors = split_names(v["analysis"].get("author"))
        if not authors or any(is_unknown_author(a) or _name_tokens(a) == owner_tokens for a in authors):
            suspects.append(k)
    return suspects

def record(log, path, **fields):
    log[path] = {**fields, "processed": datetime.now().isoformat(), **fingerprint(path)}

def main():
    # Hantera kommandoradsargument
    parser = argparse.ArgumentParser(description="Analysera dokument i en mapp")
    parser.add_argument("--folder", type=str, help="Mapp att analysera (överskriver config.yaml)")
    parser.add_argument("--noris", action="store_true", help="Skapa ingen Zotero RIS-fil")
    parser.add_argument("--refresh", action="store_true", help="Radera loggen och analysera allt från scratch")
    parser.add_argument("--force", nargs="+", metavar="FIL", default=[],
                        help="Analysera angivna filer på nytt även om de inte ändrats")
    parser.add_argument("--recheck-owner", action="store_true",
                        help="Analysera om äldre poster där arkivägaren eller ingen alls står som författare")
    parser.add_argument("--check", action="store_true",
                        help="Visa vad som skulle göras, utan att anropa Claude eller ändra något")
    args = parser.parse_args()

    config = load_config()

    # Arkivägaren – används bara för att hindra att hans namn sätts utan belägg.
    # default_author är det gamla namnet på inställningen.
    owner = config.get("archive_owner") or config.get("default_author") or ""

    # Överskrid config om --folder angivits
    if args.folder:
        config["folders"] = [str(Path(args.folder).resolve())]

    # Validera filnamn i alla mappar innan något annat körs
    for folder in config["folders"]:
        validate_filenames(folder)

    # Definiera alla sökvägar tidigt
    folder = config["folders"][0]
    folder_name = Path(folder).name
    base_output = Path(folder) / "analyzer"
    log_path = str(base_output / "processed_files.json")
    report_path = str(base_output / f"analys-{folder_name}.docx")
    zotero_path = str(base_output / f"zotero-import-{folder_name}.ris")
    extensions = [e.lower() for e in config["extensions"]]

    if args.refresh and not args.check:
        if Path(log_path).exists():
            Path(log_path).unlink()
            print("Logg raderad - analyserar allt från scratch.")
        log = {}
    else:
        log = load_log(log_path)
    if args.check:
        log = copy.deepcopy(log)

    # Rensa bort poster för filer som inte längre finns eller bytt skiftläge
    print(f"Kontrollerar registret...")
    log = reconcile_registry(log)

    changed, backfilled = detect_changes(log)
    if backfilled:
        print(f"  Fingeravtryck (storlek, mtime, SHA-256) tillagda för {backfilled} äldre poster.")
    forget_changed(log, changed)

    forced = resolve_forced(log, args.force, folder)
    if args.recheck_owner:
        forced += owner_suspects(log, owner)
    for key in dict.fromkeys(forced):
        removed = drop_group(log, key)
        if removed:
            print(f"  Analyseras om: {' + '.join(Path(p).name for p in removed)}")

    if not args.check:
        save_log(log_path, log)

    file_groups, additions = find_files(config["folders"], extensions, log)

    if args.check:
        broken = [(k, v.get("reason")) for k, v in log.items() if entry_role(v) == "broken"]
        dups = [k for k, v in log.items() if v.get("identical_bytes")]
        print(f"\nPoster i registret: {len(log)}")
        print(f"Grupper att analysera: {len(file_groups)}")
        for g in file_groups:
            print(f"  + {' + '.join(Path(p).name for p in g)}")
        for primary, new in additions:
            print(f"  ~ {' + '.join(Path(p).name for p in new)} läggs till {Path(primary).name}")
        for path, reason in broken:
            print(f"  ✗ Trasig: {Path(path).name} – {reason}")
        for d in dups:
            print(f"  = Dubblett: {Path(d).name} → {Path(log[d]['primary']).name}")
        for name in unanalyzed_files(folder, extensions):
            print(f"  · Analyseras inte (filtyp): {name}")
        return

    # Nya filer bredvid ett redan analyserat verk blir sekundära poster
    for primary, new in additions:
        analysis = log[primary]["analysis"]
        for p in new:
            record(log, p, role="secondary", primary=primary, identical_bytes=False)
            analysis.setdefault("all_filepaths", [primary]).append(p)
            if Path(p).suffix.lower() == ".pdf" and Path(analysis.get("filepath", "")).suffix.lower() != ".pdf":
                analysis["filepath"] = p
        print(f"  Tillagd till {Path(primary).name}: {' + '.join(Path(p).name for p in new)}")
    if additions:
        save_log(log_path, log)

    client = anthropic.Anthropic()

    print(f"Startar analys: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Redan processade filer: {len(log)}")
    print(f"Nya grupper att processa: {len(file_groups)}\n")

    # Hashar för att känna igen byte-identiska kopior med olika namn
    hash_index = {v["sha256"]: k for k, v in log.items() if entry_role(v) == "primary" and v.get("sha256")}

    results = []

    for i, group in enumerate(file_groups, 1):
        label = " + ".join(Path(p).name for p in group)
        print(f"[{i}/{len(file_groups)}] Analyserar: {label}")

        # Tomma filer markeras som trasiga var för sig; resten av gruppen analyseras
        for p in [p for p in group if Path(p).stat().st_size == 0]:
            print(f"  ✗ Tom fil (0 byte) – markeras som trasig: {Path(p).name}")
            record(log, p, role="broken", reason="tom fil (0 byte)")
            group.remove(p)
        if not group:
            save_log(log_path, log)
            continue

        # Läs från första läsbara filen i gruppen (epub > pdf per prioritetssortering)
        content = None
        for p in list(group):
            content = read_file(p, config)
            if content and len(content.strip()) >= 50:
                break
            print(f"  ✗ Tomt eller oläsbart innehåll – markeras som trasig: {Path(p).name}")
            record(log, p, role="broken", reason="ingen läsbar text (skannad eller skadad fil?)")
            group.remove(p)
            content = None
        if not content:
            save_log(log_path, log)
            continue
        primary = group[0]

        digest = sha256_file(primary)
        if digest in hash_index and hash_index[digest] in log:
            original = hash_index[digest]
            print(f"  = Byte-identisk med {Path(original).name} – registreras som dubblett")
            for p in group:
                record(log, p, role="secondary", primary=original, duplicate_of=original,
                       identical_bytes=(p == primary))
                log[original]["analysis"].setdefault("all_filepaths", [original]).append(p)
            save_log(log_path, log)
            continue

        try:
            analysis = analyze_document(client, config, primary, content, owner)
            analysis["all_filepaths"] = group
            # RIS-posten ska peka på PDF om sådan finns, annars primary
            pdf_paths = [p for p in group if Path(p).suffix.lower() == ".pdf"]
            analysis["filepath"] = pdf_paths[0] if pdf_paths else primary
            results.append(analysis)

            record(log, primary, role="primary", schema_version=SCHEMA_VERSION,
                   title=analysis.get("title"), author=analysis.get("author"), analysis=analysis)
            # Markera även övriga filer i gruppen som processade
            for p in group[1:]:
                record(log, p, role="secondary", primary=primary, identical_bytes=False)
            hash_index[log[primary]["sha256"]] = primary
            save_log(log_path, log)
            flags = ""
            if analysis.get("ai_generated") in ("ja", "misstänkt"):
                flags = f"  [AI: {analysis['ai_generated']}]"
            print(f"  ✓ {analysis.get('author') or 'Okänd'} – {analysis.get('title', 'Utan titel')}{flags}")

        except Exception as e:
            print(f"  ✗ Fel vid analys: {e}")

    print(f"\nKlart! {len(results)} dokument analyserade.")

    # Bygg lista med alla resultat - nya + tidigare analyserade
    all_results = [entry["analysis"] for entry in log.values() if entry_role(entry) == "primary"]
    duplicates = [(k, v["primary"]) for k, v in log.items() if v.get("identical_bytes")]
    broken = [(k, v.get("reason", "okänt fel")) for k, v in log.items() if entry_role(v) == "broken"]

    print(f"Totalt i rapport: {len(all_results)} dokument.")

    generate_word_report(all_results, report_path, folder_name,
                         duplicates=duplicates, broken=broken,
                         unanalyzed=unanalyzed_files(folder, extensions))
    if not args.noris:
        generate_zotero_export(all_results, zotero_path)

if __name__ == "__main__":
    main()
