"""Tests for /tables routes.

Covers:
- POST / + GET / round trip
- POST /{table_id}/start dispatch
- PATCH /{table_id}/columns/{column_id} rename
- POST /propose-columns (mocked OpenAI)
- /start is idempotent (second call returns 0 cells once first call has set
  pending->working)
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import Cell, Row, TableColumn


async def _create_basic_table(client, columns=None):
    if columns is None:
        columns = [
            {
                "name": "Background",
                "description": "Academic background",
                "output_type": "short_text",
                "required_evidence": False,
            },
            {
                "name": "Specialty",
                "description": "Area of expertise",
                "output_type": "short_text",
                "required_evidence": True,
            },
        ]
    resp = await client.post(
        "/tables",
        json={"research_goal": "compare arbitrators", "columns": columns},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_create_and_get_table(client):
    body = await _create_basic_table(client)
    table_id = body["id"]

    # 5 predefined rows x 2 columns = 10 cells
    assert len(body["rows"]) == 5
    assert len(body["columns"]) == 2
    assert len(body["cells"]) == 10
    assert body["status"] == "draft"
    assert body["research_goal"] == "compare arbitrators"

    # GET it back
    resp = await client.get(f"/tables/{table_id}")
    assert resp.status_code == 200
    fetched = resp.json()
    assert fetched["id"] == table_id
    assert len(fetched["rows"]) == 5
    assert len(fetched["columns"]) == 2
    assert len(fetched["cells"]) == 10
    # all cells start pending
    assert all(c["status"] == "pending" for c in fetched["cells"])


@pytest.mark.asyncio
async def test_get_table_404(client):
    resp = await client.get("/tables/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_column(client, session_factory):
    body = await _create_basic_table(client)
    table_id = body["id"]
    col_id = body["columns"][0]["id"]

    resp = await client.patch(
        f"/tables/{table_id}/columns/{col_id}",
        json={"name": "Renamed Column"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Column"

    # confirm it persisted
    async with session_factory() as db:
        col = await db.get(TableColumn, col_id)
        assert col.name == "Renamed Column"


@pytest.mark.asyncio
async def test_rename_column_404(client):
    body = await _create_basic_table(client)
    table_id = body["id"]

    resp = await client.patch(
        f"/tables/{table_id}/columns/does-not-exist",
        json={"name": "X"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rename_column_wrong_table(client):
    """Rename should 404 if the column belongs to a different table."""
    body_a = await _create_basic_table(client)
    body_b = await _create_basic_table(client)

    table_a = body_a["id"]
    col_b = body_b["columns"][0]["id"]

    resp = await client.patch(
        f"/tables/{table_a}/columns/{col_b}",
        json={"name": "X"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_start_table_dispatches_cells(client, session_factory):
    body = await _create_basic_table(client)
    table_id = body["id"]
    expected_cells = len(body["cells"])

    dispatched: list[str] = []

    with patch("app.orchestrator.enqueue_cell", side_effect=dispatched.append):
        resp = await client.post(f"/tables/{table_id}/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["cell_count"] == expected_cells
        assert len(dispatched) == expected_cells

    # table marked running
    async with session_factory() as db:
        from app.models import Table

        t = await db.get(Table, table_id)
        assert t.status == "running"


@pytest.mark.asyncio
async def test_start_table_idempotent_shrinks(client, session_factory):
    """Calling /start twice should not re-dispatch already-working/done cells."""
    body = await _create_basic_table(client)
    table_id = body["id"]
    expected_cells = len(body["cells"])

    dispatched: list[str] = []

    with patch("app.orchestrator.enqueue_cell", side_effect=dispatched.append):
        resp1 = await client.post(f"/tables/{table_id}/start")
        assert resp1.status_code == 200
        assert resp1.json()["cell_count"] == expected_cells

        # Simulate the worker having flipped cells to "working".
        async with session_factory() as db:
            cells = (await db.execute(select(Cell).where(Cell.table_id == table_id))).scalars().all()
            for c in cells:
                c.status = "working"
            await db.commit()

        first_dispatched = len(dispatched)

        resp2 = await client.post(f"/tables/{table_id}/start")
        assert resp2.status_code == 200
        assert resp2.json()["cell_count"] == 0
        # No new dispatches.
        assert len(dispatched) == first_dispatched


@pytest.mark.asyncio
async def test_start_table_404(client):
    resp = await client.post("/tables/nope/start")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_propose_columns(client, scripted_openai_factory):
    """propose_columns route uses OpenAI tool calls; mock the response."""
    from tests.conftest import make_response, make_tool_call

    proposed = {
        "columns": [
            {
                "name": "Experience",
                "description": "Years of experience",
                "output_type": "short_text",
                "required_evidence": False,
            },
            {
                "name": "Specialty",
                "description": "Area",
                "output_type": "short_text",
                "required_evidence": True,
            },
            {
                "name": "Awards",
                "description": "Notable awards",
                "output_type": "list",
                "required_evidence": False,
            },
            {
                "name": "Publications",
                "description": "Notable publications",
                "output_type": "list",
                "required_evidence": False,
            },
        ]
    }
    response = make_response(tool_calls=[make_tool_call("propose_columns", proposed)])
    scripted_openai_factory([response])

    resp = await client.post(
        "/tables/propose-columns",
        json={"research_goal": "expertise comparison"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["columns"]) == 4
    assert data["columns"][0]["name"] == "Experience"
    assert data["columns"][1]["required_evidence"] is True
