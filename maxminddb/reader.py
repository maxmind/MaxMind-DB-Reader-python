"""Pure-Python reader for the MaxMind DB file format."""

from __future__ import annotations

try:
    import mmap
except ImportError:
    mmap = None  # type: ignore[assignment]

import contextlib
import io
import ipaddress
import operator
import os
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from typing import TYPE_CHECKING, Any

from maxminddb.const import MODE_AUTO, MODE_FD, MODE_FILE, MODE_MEMORY, MODE_MMAP
from maxminddb.decoder import Decoder
from maxminddb.errors import InvalidDatabaseError
from maxminddb.file import FileBuffer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from typing_extensions import Self

    from maxminddb.types import (
        DatabaseSource,
        Record,
        RecordDict,
        StrOrBytesPath,
    )

_IPV4_MAX_NUM = 2**32
# The path types, which the C extension also accepts.
_PATH_TYPES = (str, bytes, os.PathLike)
# The database types that the path modes pass to open().
_PATH_OR_FD_TYPES = (*_PATH_TYPES, int)


class Reader:
    """A pure Python implementation of a reader for the MaxMind DB format.

    IP addresses can be looked up using the ``get`` method.
    """

    _DATA_SECTION_SEPARATOR_SIZE = 16
    _METADATA_START_MARKER = b"\xab\xcd\xefMaxMind.com"

    _buffer: bytes | bytearray | FileBuffer | "mmap.mmap"  # noqa: UP037
    _buffer_size: int
    closed: bool
    _decoder: Decoder
    _metadata: Metadata
    _record_size: int
    _ipv4_start: int
    _search_tree_size: int
    _data_start: int

    def __init__(
        self,
        database: DatabaseSource,
        mode: int = MODE_AUTO,
    ) -> None:
        """Reader for the MaxMind DB file format.

        Arguments:
            database: A path to a valid MaxMind DB file such as a GeoIP database
                      file, or a binary file object for MODE_FD or MODE_AUTO.
                      MODE_AUTO, MODE_MMAP, MODE_FILE and MODE_MEMORY also
                      accept the file descriptor of a regular file. MODE_MEMORY
                      reads it from its current offset, the others from the
                      start. The reader closes it, even when the file is not a
                      valid database.
            mode: mode to open the database with. Valid mode are:
                  * MODE_MMAP - read from memory map.
                  * MODE_FILE - read database as standard file.
                  * MODE_MEMORY - load database into memory.
                  * MODE_AUTO - tries MODE_MMAP and then MODE_FILE. Reads a
                                file object into memory, as MODE_FD does.
                                Default.
                  * MODE_FD - the param passed via database is a binary file
                              object, not a path. This mode implies MODE_MEMORY.

        """
        filename = self._load_buffer(database, mode)

        # Include validation errors in this cleanup scope. TRY301 is suppressed
        # because the handler only closes the buffer and re-raises the error.
        try:
            metadata_start = self._buffer.rfind(
                self._METADATA_START_MARKER,
                max(0, self._buffer_size - 128 * 1024),
            )

            if metadata_start == -1:
                msg = (
                    f"Error opening database file ({filename}). "
                    "Is this a valid MaxMind DB file?"
                )
                raise InvalidDatabaseError(  # noqa: TRY301
                    msg,
                )

            metadata_start += len(self._METADATA_START_MARKER)
            metadata_decoder = Decoder(self._buffer, metadata_start)
            try:
                (metadata, _) = metadata_decoder.decode(metadata_start)
            except (TypeError, UnicodeDecodeError) as e:
                # For example, a map key that is a list, or a string that is
                # not UTF-8. The C extension raises InvalidDatabaseError too.
                msg = f"Error reading metadata in database file ({filename})."
                raise InvalidDatabaseError(msg) from e

            if not isinstance(metadata, dict):
                msg = f"Error reading metadata in database file ({filename})."
                raise InvalidDatabaseError(  # noqa: TRY301
                    msg,
                )

            self._metadata = Metadata(**_metadata_fields(metadata, filename))
            self._record_size = self._metadata.record_size

            # _resolve_data_pointer uses these on every lookup.
            self._search_tree_size = self._metadata.search_tree_size
            self._data_start = (
                self._search_tree_size + self._DATA_SECTION_SEPARATOR_SIZE
            )

            # Traversal reads nodes below node_count. Once the tree fits, those
            # reads need no length checks of their own.
            if self._data_start > self._buffer_size:
                msg = (
                    f"Error opening database file ({filename}). The search tree "
                    "extends past the end of the file."
                )
                raise InvalidDatabaseError(msg)  # noqa: TRY301

            self._decoder = Decoder(self._buffer, self._data_start)
            self.closed = False

            ipv4_start = 0
            if self._metadata.ip_version == 6:
                # We store the IPv4 starting node as an optimization for IPv4 lookups
                # in IPv6 trees. This allows us to skip over the first 96 nodes in
                # this case.
                node = 0
                for _ in range(96):
                    if node >= self._metadata.node_count:
                        break
                    node = self._read_node(node, 0)
                ipv4_start = node
            self._ipv4_start = ipv4_start
        except BaseException:
            # Release the buffer on any initialization failure.
            self.close()
            raise

    def metadata(self) -> Metadata:
        """Return the metadata associated with the MaxMind DB file."""
        return self._metadata

    def get(self, ip_address: str | IPv6Address | IPv4Address) -> Record | None:
        """Return the record for the ip_address in the MaxMind DB.

        Arguments:
            ip_address: an IP address in the standard string notation

        """
        (record, _) = self.get_with_prefix_len(ip_address)
        return record

    def get_with_prefix_len(
        self,
        ip_address: str | IPv6Address | IPv4Address,
    ) -> tuple[Record | None, int]:
        """Return a tuple with the record and the associated prefix length.

        Arguments:
            ip_address: an IP address in the standard string notation

        """
        if isinstance(ip_address, str):
            address = ipaddress.ip_address(ip_address)
        else:
            address = ip_address

        try:
            packed_address = bytearray(address.packed)
        except AttributeError as ex:
            msg = "argument 1 must be a string or ipaddress object"
            raise TypeError(msg) from ex

        if address.version == 6 and self._metadata.ip_version == 4:
            msg = (
                f"Error looking up {ip_address}. You attempted to look up "
                "an IPv6 address in an IPv4-only database."
            )
            raise ValueError(
                msg,
            )

        (pointer, prefix_len) = self._find_address_in_tree(packed_address)

        if pointer:
            return self._resolve_data_pointer(pointer), prefix_len
        return None, prefix_len

    def __iter__(self) -> Iterator[tuple[IPv4Network | IPv6Network, Record]]:
        return self._generate_children(0, 0, 0)

    def _generate_children(
        self,
        node: int,
        depth: int,
        ip_acc: int,
    ) -> Iterator[tuple[IPv4Network | IPv6Network, Record]]:
        node_count = self._metadata.node_count
        bits = 128 if self._metadata.ip_version == 6 else 32
        # Skip the IPv4 subtree when an address with a set bit in its first 96
        # bits leads to it, as the C extension does. Inside the IPv4 subtree,
        # or in an IPv4 tree, a record that points back to it is a cycle.
        if (
            node == self._ipv4_start
            and bits == 128
            and node < node_count
            and ip_acc >> max(depth - 96, 0) != 0
        ):
            return

        if node > node_count:
            ip_acc <<= bits - depth
            network: IPv4Network | IPv6Network
            if bits == 32:
                network = IPv4Network((ip_acc, depth))
            elif depth >= 96 and ip_acc < _IPV4_MAX_NUM:
                # An IPv4 network in an IPv6 tree is at least /96, and its
                # first 96 bits are zero.
                network = IPv4Network((ip_acc, depth - 96))
            else:
                network = IPv6Network((ip_acc, depth))
            yield (network, self._resolve_data_pointer(node))
        elif node < node_count:
            # A node at the full address depth has no valid children, and no
            # record can point to the root. Only a corrupt tree, such as one
            # with a cycle, has either.
            if depth >= bits or (node == 0 and depth > 0):
                msg = "The MaxMind DB file's search tree is corrupt"
                raise InvalidDatabaseError(msg)
            left = self._read_node(node, 0)
            ip_acc <<= 1
            depth += 1
            yield from self._generate_children(left, depth, ip_acc)
            right = self._read_node(node, 1)
            yield from self._generate_children(right, depth, ip_acc | 1)

    def _find_address_in_tree(self, packed: bytearray) -> tuple[int, int]:
        bit_count = len(packed) * 8
        node = self._start_node(bit_count)
        node_count = self._metadata.node_count

        i = 0
        while i < bit_count and node < node_count:
            bit = 1 & (packed[i >> 3] >> 7 - (i % 8))
            node = self._read_node(node, bit)
            i = i + 1

        if node == node_count:
            # Record is empty
            return 0, i
        if node > node_count:
            return node, i

        msg = "Invalid node in search tree"
        raise InvalidDatabaseError(msg)

    def _start_node(self, length: int) -> int:
        if self._metadata.ip_version == 6 and length == 32:
            return self._ipv4_start
        return 0

    def _read_node(self, node_number: int, index: int) -> int:
        record_size = self._record_size
        if record_size == 28:
            # Two 28-bit records share the middle byte: its high nibble
            # belongs to the left record and its low nibble to the right.
            base_offset = node_number * 7
            if index:
                offset = base_offset + 3
                record = int.from_bytes(self._buffer[offset : offset + 4], "big")
                return record & 0x0FFFFFFF
            record = int.from_bytes(self._buffer[base_offset : base_offset + 4], "big")
            return (record >> 8) | ((record & 0xF0) << 20)
        if record_size == 24:
            offset = node_number * 6 + index * 3
            return int.from_bytes(self._buffer[offset : offset + 3], "big")
        if record_size == 32:
            offset = node_number * 8 + index * 4
            return int.from_bytes(self._buffer[offset : offset + 4], "big")
        msg = f"Unknown record size: {record_size}"
        raise InvalidDatabaseError(msg)

    def _resolve_data_pointer(self, pointer: int) -> Record:
        resolved = pointer - self._metadata.node_count + self._search_tree_size

        # A pointer into the separator between the tree and the data section
        # is as corrupt as one past the end, as libmaxminddb checks.
        if resolved < self._data_start or resolved >= self._buffer_size:
            msg = "The MaxMind DB file's search tree is corrupt"
            raise InvalidDatabaseError(msg)

        (data, _) = self._decoder.decode(resolved)
        return data

    def _load_buffer(
        self,
        database: DatabaseSource,
        mode: int = MODE_AUTO,
    ) -> object:
        """Load the database and return a name for it in error messages."""
        if mode not in (MODE_AUTO, MODE_FD, MODE_FILE, MODE_MEMORY, MODE_MMAP):
            msg = (
                f"Unsupported open mode ({mode}). Only MODE_AUTO, MODE_MMAP, "
                "MODE_FILE, MODE_MEMORY and MODE_FD are supported by the pure "
                "Python Reader"
            )
            raise ValueError(
                msg,
            )

        # bool is an int, but it is never a file descriptor.
        if mode != MODE_FD and not isinstance(database, bool):
            # open() also takes an object with __index__, such as numpy.int64,
            # as a file descriptor.
            if not isinstance(database, _PATH_OR_FD_TYPES) and hasattr(
                type(database), "__index__"
            ):
                database = operator.index(database)  # type: ignore[arg-type]
            # A path wins over read(), because some path objects also have a
            # text read(). MODE_FD reads any object with read().
            if isinstance(database, _PATH_OR_FD_TYPES):
                return self._load_path(database, mode)
        # MODE_AUTO reads a file object into memory, as MODE_FD does.
        read = getattr(database, "read", None)
        if mode in (MODE_AUTO, MODE_FD) and callable(read):
            return self._load_file_object(database, read)
        if mode == MODE_AUTO:
            hint = "Pass a path or a binary file object."
        elif mode == MODE_FD:
            hint = (
                "MODE_FD takes a binary file object. Use MODE_MMAP, MODE_FILE "
                "or MODE_MEMORY for a path or a file descriptor."
            )
        else:
            hint = "Pass a path or a file descriptor. Use MODE_FD for a file object."
        msg = f"Unsupported database type ({type(database).__name__}). {hint}"
        raise TypeError(msg)

    def _load_path(self, database: StrOrBytesPath | int, mode: int) -> object:
        """Memory-map or read a path or file descriptor."""
        if (mode == MODE_AUTO and mmap) or mode == MODE_MMAP:
            with open(database, "rb") as db_file:
                self._buffer = mmap.mmap(db_file.fileno(), 0, access=mmap.ACCESS_READ)
                self._buffer_size = self._buffer.size()
        elif mode in (MODE_AUTO, MODE_FILE):
            self._buffer = FileBuffer(database)
            self._buffer_size = self._buffer.size()
        else:
            with open(database, "rb") as db_file:
                buf = db_file.read()
                self._buffer = buf
                self._buffer_size = len(buf)
        return database

    def _load_file_object(self, database: object, read: Callable[[], object]) -> object:
        """Read a binary file object into memory."""
        # A text file can fail to decode inside read(), so check it first.
        if isinstance(database, io.TextIOBase):
            msg = (
                f"The database file object is a text file "
                f"({type(database).__name__}). Open it in binary mode."
            )
            raise TypeError(msg)
        buf = read()
        if not isinstance(buf, (bytes, bytearray)):
            msg = f"The database file object returned {type(buf).__name__}, not bytes."
            if isinstance(buf, str):
                msg += " Open it in binary mode."
            raise TypeError(msg)
        self._buffer = buf
        self._buffer_size = len(buf)
        # io buffers are not guaranteed to have a name attribute
        if hasattr(database, "name"):
            return database.name
        return f"<{type(database)}>"

    def close(self) -> None:
        """Close the MaxMind DB file and returns the resources to the system.

        Calling this method while reads are in progress may cause exceptions.
        """
        with contextlib.suppress(AttributeError):
            self._buffer.close()  # type: ignore[union-attr]

        self.closed = True

    def __exit__(self, *_: object) -> None:
        self.close()

    def __enter__(self) -> Self:
        if self.closed:
            msg = "Attempt to reopen a closed MaxMind DB"
            raise ValueError(msg)
        return self


# The type of each metadata value. libmaxminddb also rejects a database with a
# missing key or a value of another type. It also checks the width and sign of
# each integer, which the decoder does not report.
_METADATA_TYPES: dict[str, type] = {
    "binary_format_major_version": int,
    "binary_format_minor_version": int,
    "build_epoch": int,
    "database_type": str,
    "description": dict,
    "ip_version": int,
    "languages": list,
    "node_count": int,
    "record_size": int,
}


# The size in bits of each unsigned integer metadata value in libmaxminddb.
_METADATA_UINT_BITS: dict[str, int] = {
    "binary_format_major_version": 16,
    "binary_format_minor_version": 16,
    "build_epoch": 64,
    "ip_version": 16,
    "node_count": 32,
    "record_size": 16,
}


def _metadata_fields(metadata: RecordDict, filename: object) -> dict[str, Any]:
    """Return the known metadata fields after a check of their types.

    A new minor version of the format can add keys. This ignores them.
    """
    prefix = f"Error reading metadata in database file ({filename})."
    fields: dict[str, Any] = {}
    for key, value_type in _METADATA_TYPES.items():
        value = metadata.get(key)
        # The exact type check rejects bool, a subclass of int.
        valid = type(value) is value_type
        if valid and isinstance(value, list):
            valid = all(type(v) is str for v in value)
        elif valid and isinstance(value, dict):
            valid = all(type(k) is str and type(v) is str for k, v in value.items())
        if not valid:
            msg = f"{prefix} The {key} value is missing or has the wrong type."
            raise InvalidDatabaseError(msg)
        fields[key] = value

    _check_metadata_ranges(fields, prefix)
    return fields


def _check_metadata_ranges(fields: dict[str, Any], prefix: str) -> None:
    """Raise InvalidDatabaseError for a value that libmaxminddb rejects."""
    # libmaxminddb stores each integer as an unsigned value of the size in
    # _METADATA_UINT_BITS. The reader decodes only the version 2 format,
    # ip_version drives the tree walk, and record_size picks the node layout.
    # libmaxminddb also rejects node_count 0, but this reader accepts an empty
    # search tree.
    if fields["record_size"] not in (24, 28, 32):
        msg = f"{prefix} Unknown record size: {fields['record_size']}."
        raise InvalidDatabaseError(msg)
    if fields["node_count"] < 0:
        msg = f"{prefix} Invalid node count: {fields['node_count']}."
        raise InvalidDatabaseError(msg)
    for key, bits in _METADATA_UINT_BITS.items():
        if not 0 <= fields[key] < 1 << bits:
            msg = f"{prefix} The {key} value {fields[key]} is out of range."
            raise InvalidDatabaseError(msg)
    if fields["binary_format_major_version"] != 2:
        version = fields["binary_format_major_version"]
        msg = f"{prefix} Unsupported binary format version {version}."
        raise InvalidDatabaseError(msg)
    if fields["ip_version"] not in (4, 6):
        msg = f"{prefix} The ip_version is {fields['ip_version']}, not 4 or 6."
        raise InvalidDatabaseError(msg)
    if fields["build_epoch"] == 0:
        msg = f"{prefix} The build_epoch is 0."
        raise InvalidDatabaseError(msg)


@dataclass(kw_only=True, frozen=True)
class Metadata:
    """Metadata for the MaxMind DB reader."""

    binary_format_major_version: int
    """
    The major version number of the binary format used when creating the
    database.
    """

    binary_format_minor_version: int
    """
    The minor version number of the binary format used when creating the
    database.
    """

    build_epoch: int
    """The Unix epoch for the build time of the database."""

    database_type: str
    """A string identifying the database type, e.g., "GeoIP2-City"."""

    description: dict[str, str]
    """A map from locales to text descriptions of the database."""

    ip_version: int
    """
    The IP version of the data in a database. A value of "4" means the
    database only supports IPv4. A database with a value of "6" may support
    both IPv4 and IPv6 lookups.
    """

    languages: list[str]
    """A list of locale codes supported by the database."""

    node_count: int
    """The number of nodes in the database."""

    record_size: int
    """The bit size of a record in the search tree."""

    @property
    def node_byte_size(self) -> int:
        """The size of a node in bytes."""
        return self.record_size // 4

    @property
    def search_tree_size(self) -> int:
        """The size of the search tree."""
        return self.node_count * self.node_byte_size
