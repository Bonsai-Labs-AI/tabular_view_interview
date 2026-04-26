import uuid
from sqlalchemy import Column, String, Boolean, JSON, ForeignKey

from .database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class Table(Base):
    __tablename__ = "tables"

    id = Column(String, primary_key=True, default=_new_id)
    research_goal = Column(String, nullable=False)
    status = Column(String, default="draft")  # draft | running | done | failed


class Row(Base):
    __tablename__ = "rows"

    id = Column(String, primary_key=True)
    table_id = Column(String, ForeignKey("tables.id"), nullable=False)
    name = Column(String, nullable=False)


class TableColumn(Base):
    __tablename__ = "columns"

    id = Column(String, primary_key=True, default=_new_id)
    table_id = Column(String, ForeignKey("tables.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    output_type = Column(String, default="short_text")
    required_evidence = Column(Boolean, default=False)


class Cell(Base):
    __tablename__ = "cells"

    id = Column(String, primary_key=True, default=_new_id)
    table_id = Column(String, ForeignKey("tables.id"), nullable=False)
    row_id = Column(String, ForeignKey("rows.id"), nullable=False)
    # References column by display name rather than stable id.
    # Efficient for reads since name is what the UI shows anyway.
    column_name = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending | working | done | failed
    value = Column(String)
    confidence = Column(String)
    reasoning = Column(String)
    sources = Column(JSON)
