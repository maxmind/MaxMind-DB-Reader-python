"""Decoder for the MaxMind DB data section."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, ClassVar, cast

try:
    import mmap
except ImportError:
    mmap = None  # type: ignore[assignment]

from maxminddb.errors import InvalidDatabaseError

if TYPE_CHECKING:
    from collections.abc import Callable

    from maxminddb.file import FileBuffer
    from maxminddb.types import Record

    DecoderFunc = Callable[["Decoder", int, int, list[int]], tuple[Record, int]]


# Per-lookup limit on the number of values decoded, recommended by the MaxMind
# DB specification. It stops a pointer fan-out, where nested pointers to shared
# targets would otherwise cost 2**depth decode operations. The count follows
# the specification's flat rule: the root is one value, each array and map
# charges its declared children, and a pointer costs nothing beyond the value
# it resolves to, which its container already charged. The largest real
# records decode a few hundred values, so the limit leaves a wide margin.
# Pointer cycles and over-deep data are caught by an explicit, call-local depth
# limit (see ``decode``). Each level costs about two interpreter frames, so
# under CPython's default recursion limit RecursionError can fire first; decode
# converts it to the same error. The explicit limit matters when a caller has
# raised the recursion limit.
_MAX_VALUES = 1 << 16
_MAX_DEPTH = 512
# Per-lookup limit on the total string and bytes payload materialized, matching
# libmaxminddb and the Go reader. It stops a payload amplification, where many
# pointers to one large value would otherwise materialize N * size bytes from a
# small file. Each string or bytes value is charged its length wherever it is
# decoded, so re-decoding a shared target through another pointer recharges.
_MAX_PAYLOAD_BYTES = 1 << 21
# The widest fixed-width integer the format defines is the 16-byte uint128; a
# declared size past that is malformed and could copy attacker-controlled bytes.
_MAX_UINT_BYTES = 16
_MAX_INT32_BYTES = 4
_TOO_MANY_VALUES = (
    "The MaxMind DB file's data section exceeds the maximum number of values"
)
_TOO_DEEP = "The MaxMind DB file's data section exceeds the maximum depth"
_TOO_LARGE = "The MaxMind DB file's data section exceeds the maximum payload size"
_BAD_DATA = (
    "The MaxMind DB file's data section contains bad data "
    "(unknown data type or corrupt data)"
)


class Decoder:
    """Decoder for the data section of the MaxMind DB."""

    def __init__(
        self,
        database_buffer: FileBuffer | mmap.mmap | bytes,
        pointer_base: int = 0,
        pointer_test: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        """Create a Decoder for a MaxMind DB.

        Arguments:
            database_buffer: an mmap'd MaxMind DB file.
            pointer_base: the base number to use when decoding a pointer
            pointer_test: used for internal unit testing of pointer code

        """
        self._pointer_test = pointer_test
        self._buffer = database_buffer
        self._pointer_base = pointer_base

    def _decode_array(
        self,
        size: int,
        offset: int,
        budget: list[int],
    ) -> tuple[list[Record], int]:
        remaining = budget[0] - size
        if remaining < 0:
            raise InvalidDatabaseError(_TOO_MANY_VALUES)
        budget[0] = remaining
        depth = budget[1] + 1
        if depth > _MAX_DEPTH:
            raise InvalidDatabaseError(_TOO_DEEP)
        budget[1] = depth
        array = []
        for _ in range(size):
            (value, offset) = self._decode(offset, budget)
            array.append(value)
        budget[1] -= 1
        return array, offset

    def _decode_boolean(
        self,
        size: int,
        offset: int,
        _budget: list[int],
    ) -> tuple[bool, int]:
        return size != 0, offset

    def _decode_bytes(
        self,
        size: int,
        offset: int,
        budget: list[int],
    ) -> tuple[bytes, int]:
        # Charge the payload before copying so a crafted size cannot force a
        # large allocation, and so pointers reusing one target recharge.
        remaining = budget[2] - size
        if remaining < 0:
            raise InvalidDatabaseError(_TOO_LARGE)
        budget[2] = remaining
        new_offset = offset + size
        return self._buffer[offset:new_offset], new_offset

    def _decode_double(
        self,
        size: int,
        offset: int,
        _budget: list[int],
    ) -> tuple[float, int]:
        self._verify_size(size, 8)
        new_offset = offset + size
        packed_bytes = self._buffer[offset:new_offset]
        (value,) = struct.unpack(b"!d", packed_bytes)
        return value, new_offset

    def _decode_float(
        self,
        size: int,
        offset: int,
        _budget: list[int],
    ) -> tuple[float, int]:
        self._verify_size(size, 4)
        new_offset = offset + size
        packed_bytes = self._buffer[offset:new_offset]
        (value,) = struct.unpack(b"!f", packed_bytes)
        return value, new_offset

    def _decode_int32(
        self,
        size: int,
        offset: int,
        _budget: list[int],
    ) -> tuple[int, int]:
        if size > _MAX_INT32_BYTES:
            raise InvalidDatabaseError(_BAD_DATA)
        if size == 0:
            return 0, offset
        new_offset = offset + size
        packed_bytes = self._buffer[offset:new_offset]

        if size != 4:
            packed_bytes = packed_bytes.rjust(4, b"\x00")
        (value,) = struct.unpack(b"!i", packed_bytes)
        return value, new_offset

    def _decode_map(
        self,
        size: int,
        offset: int,
        budget: list[int],
    ) -> tuple[dict[str, Record], int]:
        # A map entry decodes a key and a value, so it costs two values.
        remaining = budget[0] - size * 2
        if remaining < 0:
            raise InvalidDatabaseError(_TOO_MANY_VALUES)
        budget[0] = remaining
        depth = budget[1] + 1
        if depth > _MAX_DEPTH:
            raise InvalidDatabaseError(_TOO_DEEP)
        budget[1] = depth
        container: dict[str, Record] = {}
        for _ in range(size):
            (key, offset) = self._decode(offset, budget)
            (value, offset) = self._decode(offset, budget)
            container[cast("str", key)] = value
        budget[1] -= 1
        return container, offset

    def _decode_pointer(
        self,
        size: int,
        offset: int,
        budget: list[int],
    ) -> tuple[Record, int]:
        pointer_size = (size >> 3) + 1

        buf = self._buffer[offset : offset + pointer_size]
        new_offset = offset + pointer_size

        if pointer_size == 1:
            buf = bytes([size & 0x7]) + buf
            pointer = struct.unpack(b"!H", buf)[0] + self._pointer_base
        elif pointer_size == 2:
            buf = b"\x00" + bytes([size & 0x7]) + buf
            pointer = struct.unpack(b"!I", buf)[0] + 2048 + self._pointer_base
        elif pointer_size == 3:
            buf = bytes([size & 0x7]) + buf
            pointer = struct.unpack(b"!I", buf)[0] + 526336 + self._pointer_base
        else:
            pointer = struct.unpack(b"!I", buf)[0] + self._pointer_base

        if self._pointer_test:
            return pointer, new_offset

        # The value at the pointer's position was charged by its containing
        # array or map, so the target costs nothing more. Only the depth changes.
        depth = budget[1] + 1
        if depth > _MAX_DEPTH:
            raise InvalidDatabaseError(_TOO_DEEP)
        budget[1] = depth
        (value, _) = self._decode(pointer, budget)
        budget[1] -= 1
        return value, new_offset

    def _decode_uint(
        self,
        size: int,
        offset: int,
        _budget: list[int],
    ) -> tuple[int, int]:
        # Reject a declared size past the widest defined unsigned integer before
        # copying, so a crafted size cannot force a large allocation.
        if size > _MAX_UINT_BYTES:
            raise InvalidDatabaseError(_BAD_DATA)
        new_offset = offset + size
        uint_bytes = self._buffer[offset:new_offset]
        return int.from_bytes(uint_bytes, "big"), new_offset

    def _decode_utf8_string(
        self,
        size: int,
        offset: int,
        budget: list[int],
    ) -> tuple[str, int]:
        # Charge the payload before copying so a crafted size cannot force a
        # large allocation, and so pointers reusing one target recharge.
        remaining = budget[2] - size
        if remaining < 0:
            raise InvalidDatabaseError(_TOO_LARGE)
        budget[2] = remaining
        new_offset = offset + size
        return self._buffer[offset:new_offset].decode("utf-8"), new_offset

    _type_decoder: ClassVar[dict[int, DecoderFunc]] = {
        1: _decode_pointer,
        2: _decode_utf8_string,
        3: _decode_double,
        4: _decode_bytes,
        5: _decode_uint,  # uint16
        6: _decode_uint,  # uint32
        7: _decode_map,
        8: _decode_int32,
        9: _decode_uint,  # uint64
        10: _decode_uint,  # uint128
        11: _decode_array,
        14: _decode_boolean,
        15: _decode_float,
    }

    def decode(self, offset: int) -> tuple[Record, int]:
        """Decode a section of the data section starting at offset.

        Arguments:
            offset: the location of the data structure to decode

        """
        # Bound the work per lookup so a crafted database cannot exhaust CPU or
        # memory. ``budget`` carries the remaining value count, the current
        # nested decode depth, and the remaining string and bytes payload, so
        # all three are shared across the recursion. It is call-local, which
        # keeps the decoder safe for concurrent reads. The root value is charged
        # here; containers charge their children. The explicit depth limit
        # is independent of Python's process-wide recursion limit; RecursionError
        # remains a fallback on interpreters whose stack limit is reached first.
        try:
            return self._decode(offset, [_MAX_VALUES - 1, 0, _MAX_PAYLOAD_BYTES])
        except RecursionError as ex:
            raise InvalidDatabaseError(_TOO_DEEP) from ex
        except (IndexError, struct.error) as ex:
            # Truncated data: a ctrl, size, or pointer read ran off the buffer.
            raise InvalidDatabaseError(_BAD_DATA) from ex

    def _decode(self, offset: int, budget: list[int]) -> tuple[Record, int]:
        new_offset = offset + 1
        ctrl_byte = self._buffer[offset]
        type_num = ctrl_byte >> 5
        # Extended type
        if not type_num:
            (type_num, new_offset) = self._read_extended(new_offset)

        try:
            decoder = self._type_decoder[type_num]
        except KeyError as ex:
            msg = f"Unexpected type number ({type_num}) encountered"
            raise InvalidDatabaseError(
                msg,
            ) from ex

        size = ctrl_byte & 0x1F
        # Sizes under 29 are stored in the ctrl byte, and a pointer's size bits
        # are not a size. Skip the call for that common case.
        if size >= 29 and type_num != 1:
            (size, new_offset) = self._size_from_ctrl_byte(size, new_offset)
        return decoder(self, size, new_offset, budget)

    def _read_extended(self, offset: int) -> tuple[int, int]:
        next_byte = self._buffer[offset]
        type_num = next_byte + 7
        if type_num < 7:
            msg = (
                "Something went horribly wrong in the decoder. An "
                f"extended type resolved to a type number < 8 ({type_num})"
            )
            raise InvalidDatabaseError(
                msg,
            )
        return type_num, offset + 1

    @staticmethod
    def _verify_size(expected: int, actual: int) -> None:
        if expected != actual:
            raise InvalidDatabaseError(_BAD_DATA)

    def _size_from_ctrl_byte(self, size: int, offset: int) -> tuple[int, int]:
        # Called only for size codes 29 to 31, which are followed by size bytes.
        if size == 29:
            size = 29 + self._buffer[offset]
            return size, offset + 1

        # Using unpack rather than int_from_bytes as it is faster
        # here and below.
        if size == 30:
            new_offset = offset + 2
            size_bytes = self._buffer[offset:new_offset]
            size = 285 + struct.unpack(b"!H", size_bytes)[0]
            return size, new_offset

        new_offset = offset + 3
        size_bytes = self._buffer[offset:new_offset]
        size = struct.unpack(b"!I", b"\x00" + size_bytes)[0] + 65821
        return size, new_offset
