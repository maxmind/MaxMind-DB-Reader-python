"""Types for database records and database arguments."""

from __future__ import annotations

import os
from typing import IO, TypeAlias

Primitive: TypeAlias = str | bytes | bytearray | bool | float | int

RecordList: TypeAlias = list["Record"]
"""RecordList is a type for lists in a database record."""

RecordDict: TypeAlias = dict[str, "Record"]
"""RecordDict is a type for dicts in a database record."""

Record: TypeAlias = Primitive | RecordList | RecordDict

StrOrBytesPath: TypeAlias = str | bytes | os.PathLike[str] | os.PathLike[bytes]
"""StrOrBytesPath is a type for a path to a database file."""

DatabaseSource: TypeAlias = StrOrBytesPath | int | IO[bytes]
"""DatabaseSource is a type for the database argument of a reader."""
