"""Types representing database records."""

from __future__ import annotations

from typing import TypeAlias

Primitive: TypeAlias = str | bytes | bool | float | int

RecordList: TypeAlias = list["Record"]
"""RecordList is a type for lists in a database record."""

RecordDict: TypeAlias = dict[str, "Record"]
"""RecordDict is a type for dicts in a database record."""

Record: TypeAlias = Primitive | RecordList | RecordDict
