import os
import json
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import anthropic
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Ladda API-nyckel från .env
load_dotenv()

# Ladda konfiguration
def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
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

# Läs textinnehåll från fil
def read_file(filepath):
    suffix = Path(filepath).suffix.lower()
    try:
        if suffix == ".txt":
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        elif suffix == ".docx":
            from docx import Document
            doc = Document(filepath)
            return "\n".join([p.text for p in doc.paragraphs])
        elif suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(filepath)
            return "\n".join([page.extract_text() or "" for page in reader.pages])
        else:
            return None
    except Exception as e:
        print(f"  Kunde inte läsa {filepath}: {e}")
        return None

# Analysera dokument med Claude
def analyze_document(client, model, max_tokens, filepath, content):
    prompt = f"""Analysera följande dokument och svara ENDAST med ett JSON-objekt i detta format:
{{
  "title": "dokumentets titel eller ett beskrivande namn om titel saknas",
  "author": "författare eller 'Okänd' om det inte framgår",
  "summary": "sammanfattning på svenska med 10-50 ord beroende på innehållets komplexitet",
  "type": "en av: artikel, uppsats, bok, predikan, studie, övrigt",
  "year": "utgivningsår eller null om okänt",
  "is_citable": true eller false (true om det är en akademisk artikel, uppsats eller bok)
}}

Filnamn: {Path(filepath).name}

Dokumentets innehåll (kan vara avkortat):
{content[:6000]}
"""
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    # Ta bort eventuella markdown-kodblock
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# Hitta alla filer att processa
def find_files(folders, extensions, log):
    files = []
    for folder in folders:
        for root, dirs, filenames in os.walk(folder):
            for filename in filenames:
                filepath = str(Path(root) / filename)
                if Path(filepath).suffix.lower() in extensions:
                    if filepath not in log:
                        files.append(filepath)
                    else:
                        print(f"  Hoppar över (redan processad): {filename}")
    return files

def generate_word_report(results, output_path):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc = DocxDocument()

    # Titel
    title = doc.add_heading("Dokumentanalys", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Datum
    date_para = doc.add_paragraph(f"Genererad: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph()

    # Sammanfattning
    doc.add_heading(f"Totalt analyserade dokument: {len(results)}", level=2)
    doc.add_paragraph()

    # Gruppera efter typ
    by_type = {}
    for r in results:
        t = r.get("type", "övrigt")
        by_type.setdefault(t, []).append(r)

    for doc_type, items in sorted(by_type.items()):
        doc.add_heading(doc_type.capitalize(), level=1)
        for item in items:
            # Rubrik
            h = doc.add_heading(item.get("title", "Utan titel"), level=2)
            # Författare och år
            meta = f"Författare: {item.get('author', 'Okänd')}"
            if item.get("year"):
                meta += f"  |  År: {item['year']}"
            p = doc.add_paragraph(meta)
            p.runs[0].italic = True
            # Sammanfattning
            doc.add_paragraph(item.get("summary", ""))
            doc.add_paragraph()

    doc.save(output_path)
    print(f"Word-rapport sparad: {output_path}")

def generate_zotero_export(results, output_path):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    citable = [r for r in results if r.get("is_citable")]

    type_map = {
        "artikel": "JOUR",
        "uppsats": "THES",
        "bok": "BOOK",
        "studie": "RPRT",
    }

    lines = []
    for item in citable:
        ris_type = type_map.get(item.get("type", ""), "GEN")
        lines.append(f"TY  - {ris_type}")
        lines.append(f"TI  - {item.get('title', 'Utan titel')}")

        author = item.get("author", "Okänd")
        for a in author.split(";"):
            lines.append(f"AU  - {a.strip()}")

        if item.get("year"):
            lines.append(f"PY  - {item['year']}")

        lines.append(f"N2  - {item.get('summary', '')}")
        lines.append("ER  - ")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Zotero RIS-fil sparad: {output_path} ({len(citable)} poster)")

# Huvudfunktion
def main():
    config = load_config()
    log_path = config["output"]["log"]
    log = load_log(log_path)

    client = anthropic.Anthropic()
    model = config["anthropic"]["model"]
    max_tokens = config["anthropic"]["max_tokens"]

    print(f"Startar analys: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Redan processade filer: {len(log)}")

    files = find_files(config["folders"], config["extensions"], log)
    print(f"Nya filer att processa: {len(files)}\n")

    results = []

    for i, filepath in enumerate(files, 1):
        filename = Path(filepath).name
        print(f"[{i}/{len(files)}] Analyserar: {filename}")

        content = read_file(filepath)
        if not content or len(content.strip()) < 50:
            print(f"  Hoppar över – tomt eller oläsbart innehåll")
            continue

        try:
            analysis = analyze_document(client, model, max_tokens, filepath, content)
            analysis["filepath"] = filepath
            results.append(analysis)

            # Spara till logg direkt
            log[filepath] = {
                "processed": datetime.now().isoformat(),
                "title": analysis.get("title"),
                "author": analysis.get("author")
            }
            save_log(log_path, log)
            print(f"  ✓ {analysis.get('author', 'Okänd')} – {analysis.get('title', 'Utan titel')}")

        except Exception as e:
            print(f"  ✗ Fel vid analys: {e}")

    print(f"\nKlart! {len(results)} dokument analyserade.")
    generate_word_report(results, config["output"]["report"])
    generate_zotero_export(results, config["output"]["zotero"])

if __name__ == "__main__":
    main()