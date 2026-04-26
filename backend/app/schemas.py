from typing import Optional, List
from pydantic import BaseModel


class ProposeColumnsRequest(BaseModel):
    research_goal: str


class ColumnDef(BaseModel):
    name: str
    description: str
    output_type: str
    required_evidence: bool = False


class ProposeColumnsResponse(BaseModel):
    columns: List[ColumnDef]


class ApprovedColumn(BaseModel):
    id: str
    name: str
    description: str
    output_type: str
    required_evidence: bool = False


class CreateTableRequest(BaseModel):
    research_goal: str
    columns: List[ApprovedColumn]


class ColumnOut(BaseModel):
    id: str
    name: str
    description: str
    output_type: str
    required_evidence: bool

    model_config = {"from_attributes": True}


class RowOut(BaseModel):
    id: str
    name: str

    model_config = {"from_attributes": True}


class Source(BaseModel):
    title: str
    url: str


class CellOut(BaseModel):
    id: str
    row_id: str
    column_name: str
    status: str
    value: Optional[str] = None
    confidence: Optional[str] = None
    reasoning: Optional[str] = None
    sources: Optional[List[Source]] = None

    model_config = {"from_attributes": True}


class TableOut(BaseModel):
    id: str
    research_goal: str
    status: str
    rows: List[RowOut]
    columns: List[ColumnOut]
    cells: List[CellOut]


class RenameColumnRequest(BaseModel):
    name: str
