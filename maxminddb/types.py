"""Types representing database records."""

from __future__ import annotations

from typing import AnyStr, TypeAlias

Primitive: TypeAlias = AnyStr | bool | float | int


class RecordList(list["Record"]):
    """RecordList is a type for lists in a database record."""


class RecordDict(dict[str, "Record"]):
    """RecordDict is a type for dicts in a database record."""


Record: TypeAlias = Primitive | RecordList | RecordDict
