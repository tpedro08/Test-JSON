from fastapi import FastAPI, File, UploadFile, HTTPException
from deep_translator import GoogleTranslator
import fitz  # pymupdf

CHUNK_SIZE = 4500

app = FastAPI(title="File Translation API", version="1.0.0")


def extract_text_from_txt(data: bytes) -> str:
    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError as e:
        raise ValueError(f"Could not decode file as UTF-8: {e}")
    if not text:
        raise ValueError("File is empty")
    return text


def extract_text_from_pdf(data: bytes) -> str:
    doc = fitz.open(stream=data, filetype="pdf")
    text = "\n".join(page.get_text() for page in doc).strip()
    doc.close()
    if not text:
        raise ValueError("No extractable text found in PDF (may contain only images)")
    return text


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


def translate_text(text: str) -> str:
    try:
        translated_chunks = [
            GoogleTranslator(source="en", target="es").translate(chunk)
            for chunk in chunk_text(text)
        ]
        return " ".join(translated_chunks)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Translation service error: {e}")


def detect_file_type(file: UploadFile) -> str:
    name = (file.filename or "").lower()
    content_type = file.content_type or ""
    if name.endswith(".pdf") or "pdf" in content_type:
        return "pdf"
    if name.endswith(".txt") or "text/plain" in content_type:
        return "txt"
    return ""


@app.post("/translate")
async def translate_file(file: UploadFile = File(...)):
    file_type = detect_file_type(file)
    if not file_type:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please upload a .txt or .pdf file.",
        )

    data = await file.read()

    try:
        if file_type == "pdf":
            original_text = extract_text_from_pdf(data)
        else:
            original_text = extract_text_from_txt(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    translated_text = translate_text(original_text)

    return {
        "filename": file.filename,
        "original_text": original_text,
        "translated_text": translated_text,
        "char_count": len(original_text),
    }
