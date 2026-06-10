from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Document
from ..schemas import DocumentOut

router = APIRouter()


@router.get("", response_model=List[DocumentOut])
async def list_documents(arbitrator_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Document).where(Document.arbitrator_id == arbitrator_id)
    )
    return [DocumentOut.model_validate(d) for d in result.scalars()]
