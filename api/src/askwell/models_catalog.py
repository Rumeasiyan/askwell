"""Which generation model file a hardware tier downloads. `M1-LIB-FE-052`.

Never hardcoded into a prompt or a request path (`AGENTS.md` §4) — this is
the one place the name lives, exactly the way `docs/architecture.md` §6 asks
for "selected by deployment profile". Both entries verified against the
Hugging Face registry on 2026-08-28 per `AGENTS.md` §4's registry-check rule:
`bartowski/Qwen_Qwen3.5-4B-GGUF` and `bartowski/Qwen_Qwen3.5-9B-GGUF`, both
`apache-2.0`, both ungated, sizes and sha256 read from the repo's own LFS
metadata (`GET /api/models/<repo>?blobs=true`), not from a size on a web
page.

Four hardware tiers (`hardware.py`) collapse to two models: `docs/architecture.md`
§6 gives `light` and `standard` the same `Qwen3.5 4B`, and `accelerated`
and `workstation` both a bigger model — the table's own `workstation` row
names `Qwen3.6 27B`, which has no Apache-2.0 GGUF quant published by a
verified uploader as of this check, so `workstation` uses the `accelerated`
row's `Qwen3.5 9B` until that changes. Filed as a gap rather than guessed
around; see the ticket's closing comment.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    tier: str
    display_name: str
    repo: str
    filename: str
    url: str
    size_bytes: int
    sha256: str


_QWEN_4B = ModelSpec(
    tier="light",
    display_name="Qwen3.5 4B (Q4_K_M)",
    repo="bartowski/Qwen_Qwen3.5-4B-GGUF",
    filename="Qwen_Qwen3.5-4B-Q4_K_M.gguf",
    url=(
        "https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/"
        "resolve/main/Qwen_Qwen3.5-4B-Q4_K_M.gguf"
    ),
    size_bytes=3_013_027_808,
    sha256="13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983",
)

_QWEN_9B = ModelSpec(
    tier="accelerated",
    display_name="Qwen3.5 9B (Q4_K_M)",
    repo="bartowski/Qwen_Qwen3.5-9B-GGUF",
    filename="Qwen_Qwen3.5-9B-Q4_K_M.gguf",
    url=(
        "https://huggingface.co/bartowski/Qwen_Qwen3.5-9B-GGUF/"
        "resolve/main/Qwen_Qwen3.5-9B-Q4_K_M.gguf"
    ),
    size_bytes=6_169_341_984,
    sha256="d784ce9eda1a5a7b51e8f705a9e6310844bf4f173654d115823c775fdea56d43",
)

CATALOG: dict[str, ModelSpec] = {
    "light": _QWEN_4B,
    "standard": _QWEN_4B,
    "accelerated": _QWEN_9B,
    "workstation": _QWEN_9B,
}


def spec_for_tier(tier: str) -> ModelSpec:
    return CATALOG.get(tier, _QWEN_4B)


def spec_for_sha256(digest: str) -> ModelSpec | None:
    """Which catalog entry a file's own bytes belong to, if any.

    Identity by checksum rather than by filename or by the tier the caller
    happened to ask about — `M7-OFFLINE-DEPLOY-144`'s own validation rule:
    a manually placed model is judged by what it actually is, never by what
    it was expected to be.
    """
    for spec in CATALOG.values():
        if spec.sha256 == digest:
            return spec
    return None


# The two models every tier needs besides its generation model: without them
# nothing can be indexed or searched. `M11-FIX-BE-235`: they had no download
# at all, and a release bundles no model, so no fresh install could ever
# answer a question. Verified against the Hugging Face registry on 2026-09-30
# (`GET /api/models/<repo>?blobs=true`): both ungated, `gpustack/bge-m3-GGUF`
# MIT and `gpustack/bge-reranker-v2-m3-GGUF` Apache-2.0, sizes and sha256 from
# the repo's LFS metadata. They are byte-for-byte the files the supervisor has
# been running (`bge-m3-FP16.gguf`, `bge-reranker-v2-m3-FP16.gguf`), converted
# from `BAAI/bge-m3` and `BAAI/bge-reranker-v2-m3` (`askwell.notices`).
COMPANIONS: list[ModelSpec] = [
    ModelSpec(
        tier="embedding",
        display_name="BGE-M3 (FP16)",
        repo="gpustack/bge-m3-GGUF",
        filename="bge-m3-FP16.gguf",
        url="https://huggingface.co/gpustack/bge-m3-GGUF/resolve/main/bge-m3-FP16.gguf",
        size_bytes=1_157_671_200,
        sha256="daec91ffb5dd0c27411bd71f29932917c49cf529a641d0168496c3a501e3062c",
    ),
    ModelSpec(
        tier="reranking",
        display_name="BGE reranker v2 M3 (FP16)",
        repo="gpustack/bge-reranker-v2-m3-GGUF",
        filename="bge-reranker-v2-m3-FP16.gguf",
        url=(
            "https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF/"
            "resolve/main/bge-reranker-v2-m3-FP16.gguf"
        ),
        size_bytes=1_159_776_896,
        sha256="5df93be121c09c43432102ad2b9569d369ccb85c209ca7583e8ccd28f0e41b88",
    ),
]
