"""Streamed CSV responses (F35): a header row, then one line per row of the matching JSON view."""

import csv
import io
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.responses import StreamingResponse


def _lines(columns: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for values in [columns, *([row.get(c) for c in columns] for row in rows)]:
        writer.writerow(["" if v is None else v for v in values])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()


def csv_response(file_name: str, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> StreamingResponse:
    return StreamingResponse(_lines(columns, rows), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{file_name}"'})
