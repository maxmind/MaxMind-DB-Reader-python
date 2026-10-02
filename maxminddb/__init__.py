"""Module for reading MaxMind DB files."""

from __future__ import annotations

import os
from importlib.metadata import version
from typing import TYPE_CHECKING, cast

from .const import (
    MODE_AUTO,
    MODE_FD,
    MODE_FILE,
    MODE_MEMORY,
    MODE_MMAP,
    MODE_MMAP_EXT,
    Mode,
)
from .errors import InvalidDatabaseError
from .reader import Reader

if TYPE_CHECKING:
    from .types import DatabaseSource

try:
    from . import extension as _extension
except ImportError:
    _extension = None  # type: ignore[assignment]


__all__ = [
    "MODE_AUTO",
    "MODE_FD",
    "MODE_FILE",
    "MODE_MEMORY",
    "MODE_MMAP",
    "MODE_MMAP_EXT",
    "InvalidDatabaseError",
    "Mode",
    "Reader",
    "open_database",
]


def open_database(
    database: DatabaseSource,
    mode: int = MODE_AUTO,
) -> Reader:
    """Open a MaxMind DB database.

    Arguments:
        database: A path to a valid MaxMind DB file such as a GeoIP database
                  file, or a file descriptor in the case of MODE_FD.
        mode: mode to open the database with. Valid mode are:
              * MODE_MMAP_EXT - use the C extension with memory map.
              * MODE_MMAP - read from memory map. Pure Python.
              * MODE_FILE - read database as standard file. Pure Python.
              * MODE_MEMORY - load database into memory. Pure Python.
              * MODE_FD - the param passed via database is a file descriptor, not
                          a path. This mode implies MODE_MEMORY.
              * MODE_AUTO - tries MODE_MMAP_EXT, MODE_MMAP, MODE_FILE in that
                          order. Uses MODE_FD for a file object. Default mode.

    """
    if mode not in (
        MODE_AUTO,
        MODE_FD,
        MODE_FILE,
        MODE_MEMORY,
        MODE_MMAP,
        MODE_MMAP_EXT,
    ):
        msg = f"Unsupported open mode: {mode}"
        raise ValueError(msg)

    has_extension = _extension and hasattr(_extension, "Reader")

    if mode == MODE_MMAP_EXT and not has_extension:
        msg = "MODE_MMAP_EXT requires the maxminddb.extension module to be available"
        raise ValueError(
            msg,
        )

    # The extension accepts only a path, so MODE_AUTO gives a file object to
    # the pure Python reader. It still refuses a file descriptor, as before.
    # The cast pretends the C reader is the pure Python Reader, which has the
    # same API.
    if mode in (MODE_AUTO, MODE_MMAP_EXT) and has_extension:
        if isinstance(database, (str, bytes, os.PathLike)):
            return cast("Reader", _extension.Reader(database, mode))
        if mode == MODE_MMAP_EXT or isinstance(database, int):
            msg = (
                f"The C extension requires a path ({type(database).__name__} "
                "given). Use MODE_FD for a file object, or MODE_MMAP for a "
                "file descriptor."
            )
            raise TypeError(msg)

    return Reader(database, mode)


__version__ = version("maxminddb")
