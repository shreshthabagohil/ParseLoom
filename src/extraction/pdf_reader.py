"""
PDF text extraction with multi-column detection, and the OCR-fallback
trigger. See DESIGN_DECISIONS.md, Tricky Parts 1 & 2, for the exact
reasoning -- this file is the implementation of both.
"""

import fitz

from .ocr_fallback import ocr_document

MIN_WORDS_BEFORE_OCR = 50


def _column_aware_text(page: "fitz.Page") -> str:
    """
    Reads a page's text blocks by bounding-box position instead of raw
    reading order, so a two-column resume doesn't interleave unrelated
    content from both columns mid-sentence.
    """
    blocks = page.get_text("blocks")
    page_width = page.rect.width
    midpoint = page_width / 2

    left, right = [], []
    for b in blocks:
        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
        if not text.strip():
            continue
        block_center = (x0 + x1) / 2
        if block_center < midpoint:
            left.append((y0, text))
        else:
            right.append((y0, text))

    # Only treat this as a genuine two-column layout if both sides have
    # a meaningful number of blocks. Otherwise a single stray block
    # (e.g. a name banner) shouldn't trigger a column split.
    if len(left) >= 2 and len(right) >= 2:
        left_text = "\n".join(t for _, t in sorted(left, key=lambda item: item[0]))
        right_text = "\n".join(t for _, t in sorted(right, key=lambda item: item[0]))
        return left_text + "\n" + right_text

    all_blocks = sorted(left + right, key=lambda item: item[0])
    return "\n".join(t for _, t in all_blocks)


def extract(path: str) -> tuple[str, str, list[str]]:
    """
    Returns (raw_text, parse_method, notes).
    parse_method is "text", "ocr", or "failed".
    """
    notes: list[str] = []

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 -- genuinely want to catch anything here
        return "", "failed", [f"Could not open PDF: {exc}"]

    page_texts = [_column_aware_text(page) for page in doc]
    doc.close()
    raw_text = "\n".join(page_texts).strip()
    word_count = len(raw_text.split())

    if word_count >= MIN_WORDS_BEFORE_OCR:
        return raw_text, "text", notes

    notes.append(f"Standard extraction yielded only {word_count} words -- trying OCR.")
    ocr_text = ocr_document(path)
    ocr_word_count = len(ocr_text.split())

    if ocr_word_count > word_count and ocr_word_count >= MIN_WORDS_BEFORE_OCR:
        notes.append(f"OCR fallback recovered {ocr_word_count} words.")
        return ocr_text, "ocr", notes

    notes.append(
        f"OCR fallback also yielded too little text ({ocr_word_count} words). "
        "Marking as Failed parse -- recommend human review."
    )
    return (ocr_text or raw_text), "failed", notes
