"""Round-trip tests for Pydantic schemas.

These are pure-Python tests but we mark them async so they participate in the
shared `asyncio_mode = "auto"` setup (and don't trip over the autouse async
fixtures in conftest).
"""
from __future__ import annotations

import pytest

from app.schemas import (
    ApprovedColumn,
    CellOut,
    ColumnDef,
    ColumnOut,
    CreateTableRequest,
    DocumentOut,
    ProposeColumnsRequest,
    ProposeColumnsResponse,
    RenameColumnRequest,
    RowOut,
    Source,
    TableOut,
)


@pytest.mark.asyncio
async def test_propose_columns_request_roundtrip():
    obj = ProposeColumnsRequest(research_goal="goal text")
    assert obj.research_goal == "goal text"
    assert ProposeColumnsRequest.model_validate(obj.model_dump()) == obj


@pytest.mark.asyncio
async def test_column_def_defaults():
    obj = ColumnDef(name="N", description="D", output_type="short_text")
    assert obj.required_evidence is False


@pytest.mark.asyncio
async def test_create_table_request_roundtrip():
    req = CreateTableRequest(
        research_goal="goal",
        columns=[
            ApprovedColumn(
                name="A",
                description="d",
                output_type="short_text",
                required_evidence=True,
            )
        ],
    )
    data = req.model_dump()
    assert data["columns"][0]["required_evidence"] is True
    assert CreateTableRequest.model_validate(data).columns[0].name == "A"


@pytest.mark.asyncio
async def test_propose_columns_response_roundtrip():
    resp = ProposeColumnsResponse(
        columns=[ColumnDef(name="N", description="D", output_type="short_text")]
    )
    raw = resp.model_dump()
    assert ProposeColumnsResponse.model_validate(raw) == resp


@pytest.mark.asyncio
async def test_cell_out_optional_fields_default_none():
    cell = CellOut(id="c1", row_id="r1", column_id="col1", status="pending")
    assert cell.value is None
    assert cell.confidence is None
    assert cell.reasoning is None
    assert cell.sources is None


@pytest.mark.asyncio
async def test_cell_out_with_sources():
    cell = CellOut(
        id="c1",
        row_id="r1",
        column_id="col1",
        status="done",
        value="ans",
        confidence="high",
        reasoning="r",
        sources=[Source(title="t", url="https://x.test")],
    )
    raw = cell.model_dump()
    parsed = CellOut.model_validate(raw)
    assert parsed.sources[0].url == "https://x.test"


@pytest.mark.asyncio
async def test_table_out_assembled():
    out = TableOut(
        id="t",
        research_goal="g",
        status="draft",
        rows=[RowOut(id="r1", arbitrator_id="arb_1", name="V")],
        columns=[
            ColumnOut(
                id="c1",
                name="N",
                description="D",
                output_type="short_text",
                required_evidence=False,
            )
        ],
        cells=[CellOut(id="cell1", row_id="r1", column_id="c1", status="pending")],
    )
    raw = out.model_dump()
    assert TableOut.model_validate(raw).id == "t"


@pytest.mark.asyncio
async def test_row_out_from_attributes():
    """RowOut should allow construction from a SQLAlchemy-like attribute object."""

    class Stub:
        id = "r1"
        arbitrator_id = "arb_1"
        name = "Vance"

    parsed = RowOut.model_validate(Stub())
    assert parsed.id == "r1"
    assert parsed.name == "Vance"


@pytest.mark.asyncio
async def test_rename_column_request():
    obj = RenameColumnRequest(name="New Name")
    assert obj.name == "New Name"


@pytest.mark.asyncio
async def test_document_out_from_attributes():
    class Stub:
        id = "d1"
        arbitrator_id = "arb_1"
        doc_type = "cv"
        filename = "cv.md"
        content = "body"

    parsed = DocumentOut.model_validate(Stub())
    assert parsed.filename == "cv.md"
    assert parsed.doc_type == "cv"


@pytest.mark.asyncio
async def test_propose_columns_request_requires_field():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ProposeColumnsRequest()  # type: ignore[call-arg]
