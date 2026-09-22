#!/usr/bin/env python3
"""Builds a synthetic corpus sized for latency measurement, not correctness
fixtures — `M7-PERF-TEST-167`.

    python eval/fixtures/generate_perf_corpus.py [--docs N] [--pages-per-doc N]

Every document is a multi-page PDF built the same way
`eval/fixtures/generate_corpus.py` already builds `handbook_a.pdf` (`_pdf`,
copied rather than imported — that module's own docstring gives the same
reason: `eval/` runs outside pytest and each fixture generator has to stay
self-contained). Each document carries exactly one invented, checkable fact —
a fictional company name paired with a fictional numeric policy, unique per
document — on a page chosen pseudo-randomly rather than always the first, so
retrieval cannot win by convention. `eval/fixtures/generate_questions.json`
is written alongside the corpus: one question per document, asking for that
document's own fact by its unique company name, with the expected substring
recorded for a caller that wants to check groundedness rather than only
latency (this ticket measures latency; the substring is there for the next
one that wants both from the same corpus rather than a second generator).

**Corpus scale is a documented compromise, not the ticket's own 200,000-chunk
scenario.** That scenario is itself named as "the finding" — evidence for
where to optimise once retrieal is shown to dominate at scale — not a bar
this harness must clear to report honestly. `--docs 80` (default) produces
roughly 240 pages / 1,000-2,000 chunks depending on the chunker's own page
splitting; `--docs 2000 --pages-per-doc 6` gets within reach of the ticket's
own regime on this machine's disk and CPU-embedding budget, at the cost of an
ingestion run measured in hours rather than minutes. The default stays small
enough to run in one sitting; anyone chasing the 200k-chunk regime passes a
larger `--docs` explicitly and should expect ingestion, not generation, to be
the long pole.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "perf_corpus"
QUESTIONS_PATH = Path(__file__).resolve().parent / "perf_corpus_questions.json"

# A closed, invented vocabulary — no company, product or number here is real,
# so no question this corpus poses can be answered from a model's general
# knowledge (the same reason `generate_corpus.py` invents "Meridian Loom").
_COMPANY_PREFIXES = [
    "Aldergate",
    "Brindlewood",
    "Cassowary",
    "Driftmarch",
    "Emberlynn",
    "Farrowdale",
    "Greywick",
    "Halcyon",
    "Ironvale",
    "Juniper Holt",
    "Kestrel Bay",
    "Larkspur",
    "Maple Ferry",
    "Norwood Quay",
    "Oakhollow",
    "Pemberton",
    "Quillfeather",
    "Rowancross",
    "Silverbrook",
    "Thistledown",
]
_COMPANY_SUFFIXES = ["Logistics", "Textiles", "Robotics", "Analytics", "Foundry", "Systems"]

_POLICY_TEMPLATES = [
    ("onboarding period", "{company}'s standard employee onboarding period lasts {n} days."),
    (
        "equipment reimbursement",
        "{company} reimburses remote-work equipment up to ${n} per employee.",
    ),
    (
        "support response target",
        "{company}'s customer support first-response target is {n} hours.",
    ),
    (
        "credential rotation",
        "{company} rotates its production database credentials every {n} days.",
    ),
    ("equipment budget", "{company}'s annual equipment budget per department is ${n} thousand."),
    ("restock cycle", "{company}'s warehouse restock cycle runs every {n} days."),
]

_FILLER_SENTENCES = [
    "This section describes routine operating procedure with no exceptions noted.",
    "Staff should consult their department lead for any deviation from this process.",
    "The following paragraph exists to give this page realistic length and density.",
    "Nothing in this paragraph changes any figure stated elsewhere in this document.",
    "Revision history for this section is maintained separately by document control.",
    "This page intentionally restates general context before the next section begins.",
    "Readers already familiar with this material may skip ahead without losing context.",
    "The procedure outlined here has been in effect since the document's last revision.",
]


def _pdf(*pages: str) -> bytes:
    """One page per string, real vector text pdfium can extract — copied
    from `eval/fixtures/generate_corpus.py::_pdf`, byte-for-byte, per that
    module's own note that each fixture generator stays self-contained."""
    count = len(pages)
    font_number = 3 + count
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + i} 0 R' for i in range(count))}] "
        f"/Count {count} >>".encode(),
    ]
    for page_index in range(count):
        content_number = font_number + 1 + page_index
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_number} 0 R >>".encode()
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page in pages:
        lines = [page[i : i + 92] for i in range(0, len(page), 92)]
        ops = " ".join(f"({line}) Tj 0 -16 Td" for line in lines)
        content = f"BT /F1 12 Tf 72 700 Td {ops} ET".encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")

    body = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    body += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(body)


def _company_name(index: int, rng: random.Random) -> str:
    # Deterministic per index (seeded rng), not per-run random, so a
    # regenerated corpus at the same `--docs`/`--seed` reproduces the same
    # facts and questions — `generate_corpus.py`'s own reproducibility bar.
    prefix = _COMPANY_PREFIXES[index % len(_COMPANY_PREFIXES)]
    suffix = _COMPANY_SUFFIXES[(index // len(_COMPANY_PREFIXES)) % len(_COMPANY_SUFFIXES)]
    disambiguator = index // (len(_COMPANY_PREFIXES) * len(_COMPANY_SUFFIXES))
    name = f"{prefix} {suffix}"
    return f"{name} {disambiguator}" if disambiguator else name


def build_document(
    index: int, pages_per_doc: int, rng: random.Random
) -> tuple[bytes, str, str, str]:
    company = _company_name(index, rng)
    topic, template = rng.choice(_POLICY_TEMPLATES)
    value = rng.randint(3, 995)
    fact = template.format(company=company, n=value)
    fact_page = rng.randrange(pages_per_doc)

    pages = []
    for page_index in range(pages_per_doc):
        sentences = [rng.choice(_FILLER_SENTENCES) for _ in range(6)]
        if page_index == fact_page:
            sentences.insert(rng.randrange(len(sentences) + 1), fact)
        pages.append(" ".join(sentences))
    return _pdf(*pages), fact, company, topic


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--docs", type=int, default=80)
    parser.add_argument("--pages-per-doc", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--questions-out", type=Path, default=QUESTIONS_PATH)
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    questions = []
    for index in range(args.docs):
        data, fact, company, topic = build_document(index, args.pages_per_doc, rng)
        filename = f"policy_{index:05d}.pdf"
        (args.out_dir / filename).write_bytes(data)
        questions.append(
            {
                "question": f"What is {company}'s {topic}?",
                "filename": filename,
                "expected_substring": fact,
            }
        )

    args.questions_out.write_text(json.dumps(questions, indent=2) + "\n")
    print(  # noqa: T201 - a build script
        f"wrote {args.docs} documents ({args.pages_per_doc} pages each) to {args.out_dir}\n"
        f"wrote {len(questions)} questions to {args.questions_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
