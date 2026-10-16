"""Types for database records and database arguments."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, AnyStr, Protocol, TypeAlias

if TYPE_CHECKING:
    Primitive: TypeAlias = str | bytes | bytearray | bool | float | int
    """Primitive is a type for a scalar value in a database record."""
else:
    # The 3.2.0 definition, so that a subscript such as Record[str] works
    # and means the same at runtime. Keep it when the static alias changes.
    # Type checkers reject the subscript.
    Primitive: TypeAlias = AnyStr | bool | float | int

RecordList: TypeAlias = list["Record"]
"""RecordList is a type for lists in a database record."""

RecordDict: TypeAlias = dict[str, "Record"]
"""RecordDict is a type for dicts in a database record."""

Record: TypeAlias = Primitive | RecordList | RecordDict
"""Record is a type for a value in a database record."""

StrOrBytesPath: TypeAlias = str | bytes | os.PathLike[str] | os.PathLike[bytes]
"""StrOrBytesPath is a type for a path to a database file."""


class SupportsRead(Protocol):
    """SupportsRead is a type for a binary file object for MODE_FD or MODE_AUTO."""

    def read(self) -> bytes:
        """Return the remaining bytes."""


DatabaseSource: TypeAlias = StrOrBytesPath | int | SupportsRead
"""DatabaseSource is a type for the database argument of a reader."""
