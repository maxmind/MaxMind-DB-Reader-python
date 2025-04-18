"""Types representing database records."""

from typing import AnyStr, Dict, List, Union

Primitive = Union[AnyStr, bool, float, int]
Record = Union[Primitive, "RecordList", "RecordDict"]


class RecordList(List[Record]):  # pylint: disable=too-few-public-methods
    """RecordList is a type for lists in a database record."""


class RecordDict(Dict[str, Record]):  # pylint: disable=too-few-public-methods
    """RecordDict is a type for dicts in a database record."""
