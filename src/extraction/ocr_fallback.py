"""
OCR fallback for scanned resumes. Only called when standard text
extraction yields too little text -- see pdf_reader.py and
DESIGN_DECISIONS.md, Tricky Part 2.
"""

import io

import fitz
import pytesseract
from PIL import Image


def ocr_document(path: str, dpi: int = 300) -> str:
    doc = fitz.open(path)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    texts = []
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        texts.append(pytesseract.image_to_string(img))
    doc.close()
    return "\n".join(texts).strip()
