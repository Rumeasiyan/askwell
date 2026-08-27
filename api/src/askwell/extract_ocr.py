"""OCR fallback with orientation detection. `M1-EXTRACT-ING-028`.

Called from `extract_pdf.run`, one page at a time, only for a page whose text
layer already failed `extract_pdf._usable` — a page with a good text layer
never touches this module. That is the ticket's own edge case ("a mixed
document — OCR runs only on the pages that need it") satisfied by where this
is called from rather than by anything in here.

**Tesseract via `pytesseract`, never a network OCR API.** C1: the binary is
bundled in the image (`api/Dockerfile`) and `pytesseract` only ever shells
out to it locally — nothing here can reach a network even if asked to.

**Orientation is detected, not guessed by trying every rotation.**
`image_to_osd` (`--psm 0`) reads a page's layout without committing to
recognising a single character first, and reports both the rotation needed to
put it right-side up and the script it looks like — one call answers both
questions the ticket's title asks for. A page OSD refuses to score — a
photograph, or too little ink to guess an angle confidently — is not a
failure of the page; it is read at zero rotation and `eng`, which is exactly
what `_ocr_page`'s `except TesseractError` below falls back to.

**Script decides the language pack, and only two exist.** `bge-m3` aside,
Askwell bundles exactly two Tesseract traineddata files: `eng` and `tam`, the
latter a hedge (`AGENTS.md` §1, `docs/decisions.md`). OSD naming any other
script still recognises as `eng` — there is no third traineddata file to fall
back to, and misreading, say, Cyrillic as Latin is a known gap for a v1 that
is English-only by design, not a bug this ticket owns. A page OSD calls
`Tamil` is recognised with `tam` and reported `supported=False`: the text
comes back, but it is never presented as Tamil support.
"""

from typing import TYPE_CHECKING, cast

import pytesseract

from askwell.logging import get_logger

if TYPE_CHECKING:
    import pypdfium2 as pdfium
    from PIL.Image import Image

log = get_logger(__name__)

# ~144 DPI (2x the PDF's 72-unit-per-inch canvas). High enough for Tesseract
# to read ordinary body text, low enough that a 900-page scan does not hold
# gigabytes of bitmaps in memory across the run — one page is rendered,
# OCR'd and discarded before the next is opened.
RENDER_SCALE = 2.0

# Tesseract's own script names, not ISO codes. Only Tamil gets its own
# traineddata; every other script name OSD can report still reads as `eng`.
_SCRIPT_LANGUAGES = {"Tamil": "tam"}
_DEFAULT_LANGUAGE = "eng"

# Languages the product advertises as supported. Tamil is a hedge: it is
# recognised so the text is not lost, but never claimed as a supported
# language (`docs/states-and-edge-cases.md` §3, `PRD.md` §8).
_SUPPORTED_LANGUAGES = frozenset({"eng"})


def _render(document: "pdfium.PdfDocument", index: int) -> "Image":  # type: ignore[no-any-unimported]
    page = document.get_page(index)
    try:
        bitmap = page.render(scale=RENDER_SCALE, grayscale=True)
        try:
            return cast("Image", bitmap.to_pil())
        finally:
            bitmap.close()
    finally:
        page.close()


def _orientation_and_language(
    image: "Image", *, document_id: str, page_number: int, filename: str
) -> tuple[int, str]:
    try:
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractError as error:
        # Too little ink to score an angle — an ordinary outcome for a blank
        # page or a photograph, not a fault. Read as-is, as English.
        log.info(
            "ocr_osd_skipped",
            document_id=document_id,
            page_number=page_number,
            filename=filename,
            reason=str(error),
        )
        return 0, _DEFAULT_LANGUAGE

    rotation = int(osd.get("rotate", 0)) % 360
    language = _SCRIPT_LANGUAGES.get(str(osd.get("script", "")), _DEFAULT_LANGUAGE)
    return rotation, language


def ocr_page(  # type: ignore[no-any-unimported]
    document: "pdfium.PdfDocument",
    index: int,
    *,
    document_id: str,
    filename: str,
) -> tuple[str | None, bool, str]:
    """The blocking half: render, orient, recognise one page.

    Run through `asyncio.to_thread` by the caller, the same way
    `extract_pdf._page_text` is — a 900-page scan reports progress between
    pages only if control returns to the event loop between them.

    Returns `(text, has_text, language)`. `text` is `None` when nothing came
    back — the "photograph with no text" edge case, recorded rather than
    treated as a fault of the page or the document.
    """
    page_number = index + 1
    image = _render(document, index)
    rotation, language = _orientation_and_language(
        image, document_id=document_id, page_number=page_number, filename=filename
    )
    if rotation:
        image = image.rotate(-rotation, expand=True)

    try:
        raw = pytesseract.image_to_string(image, lang=language)
    except pytesseract.TesseractError as error:
        log.warning(
            "ocr_recognition_failed",
            document_id=document_id,
            page_number=page_number,
            filename=filename,
            language=language,
            error=str(error),
        )
        raw = ""

    text = raw.strip()
    has_text = bool(text)

    log.info(
        "ocr_page_completed",
        document_id=document_id,
        page_number=page_number,
        filename=filename,
        has_text=has_text,
        rotation=rotation,
        language=language,
        supported=language in _SUPPORTED_LANGUAGES,
    )

    return (text if has_text else None), has_text, language
