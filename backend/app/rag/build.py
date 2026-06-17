"""Offline indexing pipeline.

Reads documents from data/documents/arb_<id>_*/*.md, chunks them, embeds
each chunk with OpenAI, and writes per-arbitrator FAISS indexes plus
chunk metadata to <rag_index_dir>/<arbitrator_id>/.

Run as:
    python -m app.rag.build              # build all arbitrators
    python -m app.rag.build --arbitrator arb_1
    python -m app.rag.build --force      # rebuild even if manifest exists
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np

from ..config import settings
from .chunker import chunk_document
from .embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, embed_texts

_log = logging.getLogger(__name__)

_CORPUS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "data" / "documents"

EMBED_BATCH_SIZE = 100


def _index_dir(arbitrator_id: str) -> Path:
    return Path(settings.rag_index_dir) / arbitrator_id


def _list_arbitrators() -> list[tuple[str, Path]]:
    """Return [(arbitrator_id, dir_path), ...] for every arb_* corpus dir."""
    if not _CORPUS_ROOT.is_dir():
        _log.warning("Corpus root does not exist: %s", _CORPUS_ROOT)
        return []
    out: list[tuple[str, Path]] = []
    for d in sorted(_CORPUS_ROOT.iterdir()):
        if not d.is_dir():
            continue
        parts = d.name.split("_", 2)
        if len(parts) < 2 or parts[0] != "arb":
            continue
        arbitrator_id = f"{parts[0]}_{parts[1]}"
        out.append((arbitrator_id, d))
    return out


def _gather_chunks(arb_dir: Path) -> tuple[list[dict], list[str]]:
    """Return (metadata, texts) for every chunk across every .md in the dir."""
    metadata: list[dict] = []
    texts: list[str] = []
    for md_file in sorted(arb_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        chunks = chunk_document(content)
        doc_type = md_file.stem
        for i, chunk in enumerate(chunks):
            metadata.append({
                "filename": md_file.name,
                "doc_type": doc_type,
                "chunk_index": i,
                "text": chunk,
            })
            texts.append(chunk)
    return metadata, texts


async def _embed_in_batches(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype="float32")
    pieces: list[np.ndarray] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        pieces.append(await embed_texts(batch))
    return np.vstack(pieces)


async def build_index_for(arbitrator_id: str, arb_dir: Path, *, force: bool) -> None:
    out_dir = _index_dir(arbitrator_id)
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists() and not force:
        _log.info("Skipping %s — manifest exists (--force to rebuild)", arbitrator_id)
        return

    metadata, texts = _gather_chunks(arb_dir)
    if not texts:
        _log.info("No .md files for %s, skipping", arbitrator_id)
        return

    _log.info("Embedding %d chunks for %s …", len(texts), arbitrator_id)
    embeddings = await _embed_in_batches(texts)

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)

    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_dir / "index.faiss"))
    with (out_dir / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for m in metadata:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    manifest = {
        "arbitrator_id": arbitrator_id,
        "num_chunks": len(texts),
        "num_documents": len({m["filename"] for m in metadata}),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": embeddings.shape[1],
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _log.info(
        "Wrote index for %s — %d chunks, %d docs → %s",
        arbitrator_id, len(texts), manifest["num_documents"], out_dir,
    )


async def main(args: argparse.Namespace) -> None:
    targets = _list_arbitrators()
    if args.arbitrator:
        targets = [t for t in targets if t[0] == args.arbitrator]
        if not targets:
            raise SystemExit(f"No corpus dir matching arbitrator id {args.arbitrator!r}")
    if not targets:
        raise SystemExit("No corpus to build.")
    for arbitrator_id, arb_dir in targets:
        await build_index_for(arbitrator_id, arb_dir, force=args.force)
    _log.info("Done.")


def cli() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Build per-arbitrator FAISS indexes.")
    parser.add_argument("--arbitrator", help="Only build this arbitrator (e.g. arb_1)")
    parser.add_argument("--force", action="store_true", help="Rebuild even if manifest exists")
    args = parser.parse_args()
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
