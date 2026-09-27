"""Example tests for ``rule_engine.drawio_model`` (honest-gates task 2.3).

These are deterministic example tests (the property-based round-trip lives in
``tests/test_drawio_model_properties.py``). They pin two things the parser must
get right on real inputs:

1. **XML safety (R1.2)** — a billion-laughs document and an external-entity
   (XXE) document both raise ``DrawioParseError("dtd-or-entity-declaration")``
   rather than expanding entities or reading a local file.
2. **Real draw.io files (R1.3, R1.4, R1.8, R1.9)** — hand-authored fixtures
   under ``tests/fixtures/drawio/`` that mirror what draw.io desktop exports:
   a multi-page ``<mxfile>``, a compressed ``<diagram>`` page, and a
   ``UserObject``/``object``-wrapped node. Their parsed page names, cell ids and
   decoded labels are asserted, and a parent-cycle fixture is asserted to raise
   ``DrawioParseError("parent-cycle:<id>")``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rule_engine.drawio_model import (
    DrawioParseError,
    absolute_origin,
    decode_compressed,
    parse_drawio,
)

FIXTURES = Path(__file__).parent / "fixtures" / "drawio"


def _parse(name: str):
    path = FIXTURES / name
    return parse_drawio(path.read_bytes(), path=str(path))


# --------------------------------------------------------------------------- #
# XML safety (R1.2)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fixture", ["billion-laughs.drawio", "xxe.drawio"])
def test_dtd_and_entity_documents_are_rejected(fixture: str) -> None:
    """A DTD / entity-declaration document raises the safety error (R1.2).

    Both the billion-laughs (internal entity expansion) and the external-entity
    (XXE ``SYSTEM``) documents must be refused before any entity is expanded or
    any external resource is read.
    """
    with pytest.raises(DrawioParseError) as excinfo:
        _parse(fixture)
    assert excinfo.value.cause == "dtd-or-entity-declaration"


# --------------------------------------------------------------------------- #
# Multi-page real draw.io export (R1.3, R1.4)
# --------------------------------------------------------------------------- #


def test_multipage_pages_ids_and_grid() -> None:
    """A two-page ``<mxfile>`` yields one Page per ``<diagram>`` (R1.3, R1.7)."""
    pages = _parse("multipage.drawio")
    assert [p.name for p in pages] == ["Overview", "Data Tier"]
    assert [p.id for p in pages] == ["page-overview-0001", "page-data-0002"]
    # gridSize is read per page (10 on the first, 20 on the second).
    assert [p.grid_size for p in pages] == [10, 20]
    # A plain (uncompressed) page is not flagged as compressed.
    assert all(not p.compressed for p in pages)


def test_multipage_cell_ids_and_labels() -> None:
    """Cell ids and decoded labels match the authored fixture (R1.4)."""
    overview, data = _parse("multipage.drawio")

    # The two model root layers ("0" and "1") plus the authored cells.
    assert set(overview.cells) == {"0", "1", "user", "lambda", "e1"}
    assert overview.cells["user"].label == "External User"
    assert overview.cells["lambda"].label == "Order Function"

    # The edge is parsed as an edge with its source/target ids.
    edge = overview.cells["e1"]
    assert edge.edge is True
    assert edge.vertex is False
    assert edge.source == "user"
    assert edge.target == "lambda"
    assert edge.label == "invoke"

    assert set(data.cells) == {"0", "1", "rds", "s3"}
    assert data.cells["rds"].label == "Orders DB"
    assert data.cells["s3"].label == "Backups"


# --------------------------------------------------------------------------- #
# Compressed page (R1.4)
# --------------------------------------------------------------------------- #


def test_compressed_page_decompresses_and_parses() -> None:
    """A compressed ``<diagram>`` body is decompressed and parsed (R1.4)."""
    (page,) = _parse("compressed.drawio")
    assert page.name == "Compressed"
    assert page.id == "page-compressed-0001"
    assert page.compressed is True
    assert set(page.cells) == {"0", "1", "api", "fn"}
    assert page.cells["api"].label == "API Gateway"
    # A `&#10;` in the compressed source survives as a real line break.
    assert page.cells["fn"].label == "Handler\nFunction"
    assert page.cells["fn"].lines == ("Handler", "Function")


def test_compressed_payload_round_trips_through_decode_compressed() -> None:
    """The fixture's payload is a genuine draw.io compressed body (R1.4).

    Decoding the raw ``<diagram>`` text with ``decode_compressed`` yields a
    ``<mxGraphModel>``, confirming the fixture uses the real
    ``base64(deflateRaw(encodeURIComponent(...)))`` pipeline rather than an
    inline model.
    """
    raw = (FIXTURES / "compressed.drawio").read_text(encoding="utf-8")
    start = raw.index("<diagram")
    body_start = raw.index(">", start) + 1
    body_end = raw.index("</diagram>", body_start)
    payload = raw[body_start:body_end].strip()
    inner = decode_compressed(payload)
    assert inner.startswith("<mxGraphModel")
    assert 'id="api"' in inner


# --------------------------------------------------------------------------- #
# UserObject / object wrappers (R1.4)
# --------------------------------------------------------------------------- #


def test_userobject_wrapper_id_label_and_attrs() -> None:
    """A ``UserObject`` node takes its id/label from the wrapper (R1.4)."""
    (page,) = _parse("userobject.drawio")
    assert set(page.cells) == {"0", "1", "payments-fn", "queue-node"}

    fn = page.cells["payments-fn"]
    assert fn.wrapper == "UserObject"
    assert fn.id == "payments-fn"
    # The wrapper label carries an HTML <br>; the html=1 inner cell means it
    # decodes to a two-line plain-text label.
    assert fn.label == "Payments\nFunction"
    assert fn.lines == ("Payments", "Function")
    assert fn.vertex is True
    # Wrapper attributes other than id/label land in wrapper_attrs.
    assert fn.wrapper_attrs["tooltip"] == "Handles payment capture"
    assert fn.wrapper_attrs["placeholders"] == "1"
    assert "id" not in fn.wrapper_attrs
    assert "label" not in fn.wrapper_attrs


def test_object_wrapper_is_supported() -> None:
    """An ``object`` wrapper is treated the same as ``UserObject`` (R1.4)."""
    (page,) = _parse("userobject.drawio")
    queue = page.cells["queue-node"]
    assert queue.wrapper == "object"
    assert queue.id == "queue-node"
    assert queue.label == "Payments Queue"
    assert queue.wrapper_attrs["queueUrl"] == "https://example/q"


# --------------------------------------------------------------------------- #
# Parent cycle (R1.8, R1.9)
# --------------------------------------------------------------------------- #


def test_parent_cycle_raises() -> None:
    """A parent cycle raises ``parent-cycle:<id>`` rather than returning (0, 0).

    The fixture parents ``alpha`` to ``beta`` and ``beta`` to ``alpha``; walking
    either cell's parent chain must fail honestly (R1.8, R1.9).
    """
    (page,) = _parse("parent-cycle.drawio")
    with pytest.raises(DrawioParseError) as excinfo:
        absolute_origin(page, "alpha")
    assert excinfo.value.cause == "parent-cycle:alpha"

    with pytest.raises(DrawioParseError) as excinfo:
        absolute_origin(page, "beta")
    assert excinfo.value.cause == "parent-cycle:beta"
