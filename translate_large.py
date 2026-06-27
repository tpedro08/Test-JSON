import sys
import json
import time
import html
from pathlib import Path
from deep_translator import GoogleTranslator
import fitz  # pymupdf
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak

CHUNK_SIZE = 4500
DELAY = 1.5        # seconds between requests
MAX_RETRIES = 5
PROGRESS_VERSION = 3


# --------------------------------------------------------------------------- #
# Extraction — keep the document structure (paragraphs + page breaks)
# --------------------------------------------------------------------------- #
def extract_units(input_path: Path) -> list[dict]:
    """Return an ordered list of units: {"para": text} or {"pb": True}."""
    suffix = input_path.suffix.lower()
    units: list[dict] = []

    if suffix == ".pdf":
        doc = fitz.open(str(input_path))
        page_count = len(doc)
        for pno, page in enumerate(doc):
            blocks = page.get_text("blocks")
            # (x0, y0, x1, y1, text, block_no, block_type) — sort top-to-bottom
            blocks = sorted(blocks, key=lambda b: (round(b[1]), round(b[0])))
            for b in blocks:
                if b[6] != 0:  # skip image blocks
                    continue
                para = " ".join(b[4].split())  # collapse intra-block line breaks
                if para:
                    units.append({"para": para})
            if pno < page_count - 1:
                units.append({"pb": True})
        doc.close()
    elif suffix == ".txt":
        raw = input_path.read_text(encoding="utf-8")
        for block in raw.split("\n\n"):
            para = " ".join(block.split())
            if para:
                units.append({"para": para})
    else:
        print(f"Error: unsupported file type '{suffix}'. Use .txt or .pdf")
        sys.exit(1)

    if not any("para" in u for u in units):
        print("Error: no extractable text found (PDF may contain only images)")
        sys.exit(1)
    return units


# --------------------------------------------------------------------------- #
# Translation
# --------------------------------------------------------------------------- #
def translate_call(text: str) -> str:
    delay = DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return GoogleTranslator(source="en", target="es").translate(text)
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Failed after {MAX_RETRIES} attempts: {e}")
            print(f"  Retry {attempt}/{MAX_RETRIES} (waiting {delay:.0f}s)...")
            time.sleep(delay)
            delay *= 2


def translate_text(text: str) -> str:
    """Translate a single paragraph, word-chunking it if it exceeds the limit."""
    if len(text) <= CHUNK_SIZE:
        return translate_call(text)
    words, chunks, current, length = text.split(), [], [], 0
    for word in words:
        word_len = len(word) + 1
        if length + word_len > CHUNK_SIZE and current:
            chunks.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += word_len
    if current:
        chunks.append(" ".join(current))
    return " ".join(translate_call(c) for c in chunks)


def translate_group(paras: list[str]) -> list[str]:
    """Translate several short paragraphs in one call, preserving boundaries."""
    if len(paras) == 1:
        return [translate_text(paras[0])]
    joined = "\n".join(paras)
    result = translate_call(joined)
    parts = result.split("\n")
    if len(parts) == len(paras):
        return parts
    # Google changed the line count — fall back to translating each separately
    return [translate_text(p) for p in paras]


# --------------------------------------------------------------------------- #
# Progress (resumable)
# --------------------------------------------------------------------------- #
def load_progress(progress_file: Path, unit_count: int) -> dict:
    if progress_file.exists():
        data = json.loads(progress_file.read_text(encoding="utf-8"))
        if data.get("version") == PROGRESS_VERSION and data.get("units") == unit_count:
            return data
        print("Existing progress is from an older version — starting fresh.\n")
    return {"version": PROGRESS_VERSION, "units": unit_count,
            "next_index": 0, "translated": []}


def save_progress(progress_file: Path, data: dict):
    progress_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# PDF rendering — preserve paragraphs, page breaks and headings
# --------------------------------------------------------------------------- #
def is_heading(text: str) -> bool:
    if len(text) > 80 or text[-1] in ".,:;":
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(c.isupper() for c in letters) / len(letters)
    return upper_ratio > 0.6


def render_pdf(translated: list[dict], output_path: Path):
    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
    )
    base = getSampleStyleSheet()["Normal"]
    body = ParagraphStyle("body", parent=base, fontName="Times-Roman",
                          fontSize=11, leading=16, spaceAfter=6,
                          alignment=TA_JUSTIFY)
    heading = ParagraphStyle("heading", parent=body, fontName="Times-Bold",
                             fontSize=14, leading=18, spaceBefore=12,
                             spaceAfter=8, alignment=TA_LEFT)

    story = []
    for item in translated:
        if item.get("pb"):
            story.append(PageBreak())
            continue
        text = (item.get("t") or "").strip()
        if not text:
            continue
        safe = html.escape(text)
        story.append(Paragraph(safe, heading if is_heading(text) else body))

    doc.build(story)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    if len(sys.argv) < 2:
        print("Usage: python translate_large.py <file.txt|file.pdf>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    output_path = input_path.with_stem(input_path.stem + "_translated").with_suffix(".pdf")
    progress_path = input_path.with_suffix(".progress.json")

    print(f"Input:    {input_path}")
    print(f"Output:   {output_path}")
    print(f"Progress: {progress_path}\n")

    units = extract_units(input_path)
    total = len(units)
    char_count = sum(len(u["para"]) for u in units if "para" in u)
    print(f"Total characters : {char_count:,}")
    print(f"Total units      : {total} (paragraphs + page breaks)")
    print(f"Estimated time   : ~{char_count / CHUNK_SIZE * DELAY / 60:.0f} minutes\n")

    progress = load_progress(progress_path, total)
    translated = progress["translated"]
    i = progress["next_index"]

    if i >= total:
        print("Translation already complete — rendering PDF...\n")
    elif i > 0:
        print(f"Resuming from unit {i}/{total} ({i/total*100:.1f}% already done)\n")

    # ----- Translation phase (resumable) ----- #
    try:
        while i < total:
            if units[i].get("pb"):
                translated.append({"pb": True})
                i += 1
            else:
                # collect consecutive paragraphs up to the char limit
                group, j, length = [], i, 0
                while j < total and "para" in units[j]:
                    plen = len(units[j]["para"]) + 1
                    if group and length + plen > CHUNK_SIZE:
                        break
                    group.append(units[j]["para"])
                    length += plen
                    j += 1
                for result in translate_group(group):
                    translated.append({"t": result})
                i = j
                if i < total:
                    time.sleep(DELAY)

            progress["translated"] = translated
            progress["next_index"] = i
            save_progress(progress_path, progress)
            print(f"\r[{i}/{total}] {i/total*100:.1f}%   ", end="", flush=True)

    except KeyboardInterrupt:
        print("\n\nInterrupted. Progress saved — run the same command to resume.")
        sys.exit(0)

    # ----- Render phase ----- #
    print("\n\nTranslation complete. Building PDF...")
    try:
        render_pdf(translated, output_path)
    except Exception as e:
        print(f"\nPDF generation failed: {e}")
        print("Your translation is safe in the progress file — "
              "fix the issue and run the same command again to re-render.")
        sys.exit(1)

    progress_path.unlink(missing_ok=True)
    print(f"\nDone! Translated PDF saved to: {output_path}")


if __name__ == "__main__":
    main()
