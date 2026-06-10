from pathlib import Path

from sqlalchemy import select

from .database import async_session
from .models import Document


_CORPUS_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "documents"


async def seed_documents() -> None:
    """Load the synthetic doc corpus into the documents table on startup.

    Idempotent: skips files already present (keyed by arbitrator_id + filename).
    """
    if not _CORPUS_ROOT.is_dir():
        return

    async with async_session() as db:
        for arb_dir in sorted(_CORPUS_ROOT.iterdir()):
            if not arb_dir.is_dir():
                continue
            parts = arb_dir.name.split("_", 2)
            if len(parts) < 2 or parts[0] != "arb":
                continue
            arbitrator_id = f"{parts[0]}_{parts[1]}"

            for md_file in sorted(arb_dir.glob("*.md")):
                existing = await db.execute(
                    select(Document).where(
                        Document.arbitrator_id == arbitrator_id,
                        Document.filename == md_file.name,
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    continue

                db.add(Document(
                    arbitrator_id=arbitrator_id,
                    doc_type=md_file.stem,
                    filename=md_file.name,
                    content=md_file.read_text(encoding="utf-8"),
                ))

        await db.commit()
