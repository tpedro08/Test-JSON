import sys
import json
import time
from pathlib import Path
from deep_translator import GoogleTranslator

CHUNK_SIZE = 4500
DELAY = 1.5        # seconds between requests
MAX_RETRIES = 5


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    words = text.split()
    chunks, current, length = [], [], 0
    for word in words:
        word_len = len(word) + 1
        if length + word_len > size and current:
            chunks.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += word_len
    if current:
        chunks.append(" ".join(current))
    return chunks


def translate_chunk(chunk: str) -> str:
    delay = DELAY
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return GoogleTranslator(source="en", target="es").translate(chunk)
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Failed after {MAX_RETRIES} attempts: {e}")
            print(f"  Retry {attempt}/{MAX_RETRIES} (waiting {delay:.0f}s)...")
            time.sleep(delay)
            delay *= 2


def load_progress(progress_file: Path) -> dict:
    if progress_file.exists():
        return json.loads(progress_file.read_text(encoding="utf-8"))
    return {"done": [], "next_index": 0}


def save_progress(progress_file: Path, data: dict):
    progress_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print("Usage: python translate_large.py <file.txt>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: file not found: {input_path}")
        sys.exit(1)

    output_path = input_path.with_stem(input_path.stem + "_translated")
    progress_path = input_path.with_suffix(".progress.json")

    print(f"Input:    {input_path}")
    print(f"Output:   {output_path}")
    print(f"Progress: {progress_path}")
    print()

    text = input_path.read_text(encoding="utf-8")
    chunks = chunk_text(text)
    total = len(chunks)
    print(f"Total characters : {len(text):,}")
    print(f"Total chunks     : {total}")
    estimated_min = (total * DELAY) / 60
    print(f"Estimated time   : ~{estimated_min:.0f} minutes")
    print()

    progress = load_progress(progress_path)
    start = progress["next_index"]
    translated = progress["done"]

    if start > 0:
        print(f"Resuming from chunk {start}/{total} ({start/total*100:.1f}% already done)\n")

    try:
        for i in range(start, total):
            chunk = chunks[i]
            percent = (i + 1) / total * 100
            print(f"[{i+1}/{total}] {percent:.1f}%  ({len(chunk)} chars)", end="", flush=True)

            result = translate_chunk(chunk)
            translated.append(result)

            print(f"  ✓", flush=True)

            progress["done"] = translated
            progress["next_index"] = i + 1
            save_progress(progress_path, progress)

            if i < total - 1:
                time.sleep(DELAY)

    except KeyboardInterrupt:
        print("\n\nInterrupted. Progress saved — run the same command to resume.")
        sys.exit(0)

    output_path.write_text(" ".join(translated), encoding="utf-8")
    progress_path.unlink(missing_ok=True)

    print(f"\nDone! Translated file saved to: {output_path}")


if __name__ == "__main__":
    main()
