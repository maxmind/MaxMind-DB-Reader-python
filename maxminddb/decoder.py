"""Decoder for the MaxMind DB data section."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

try:
    import mmap
except ImportError:
    mmap = None  # type: ignore[assignment]

from maxminddb.errors import InvalidDatabaseError

if TYPE_CHECKING:
    from maxminddb.file import FileBuffer
    from maxminddb.types import Record


# Per-lookup value limit recommended by the MaxMind DB specification. It stops
# pointer fan-out, where nested containers share targets that would otherwise
# cost 2**depth decode operations. The root costs one value. Arrays charge each
# element, maps charge each key and value, and pointers cost no extra value.
# Real records decode a few hundred values, leaving a wide margin.
# An explicit depth limit catches container cycles and overly nested data.
# Python's recursion limit may fire first, which decode converts to the same
# error. The explicit limit also applies when callers raise Python's limit.
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
# Added to a pointer value, by pointer size. A 4-byte pointer adds nothing.
_POINTER_VALUE_OFFSETS = (0, 0, 2048, 526336)
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
        decode = self._decode
        for _ in range(size):
            (value, offset) = decode(offset, budget, False)  # noqa: FBT003
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
        decode = self._decode
        for _ in range(size):
            (key, offset) = decode(offset, budget, False)  # noqa: FBT003
            (value, offset) = decode(offset, budget, False)  # noqa: FBT003
            container[key] = value  # type: ignore[index]
        budget[1] -= 1
        return container, offset

    def _decode_pointer(
        self,
        size: int,
        offset: int,
        budget: list[int],
    ) -> tuple[Record, int]:
        pointer_size = (size >> 3) + 1
        new_offset = offset + pointer_size
        pointer_bytes = self._buffer[offset:new_offset]
        if len(pointer_bytes) != pointer_size:
            raise InvalidDatabaseError(_BAD_DATA)
        pointer = int.from_bytes(pointer_bytes, "big")
        if pointer_size < 4:
            # The low three bits of the ctrl byte are the high bits of the
            # pointer, and sizes 2 and 3 add a fixed offset.
            pointer |= (size & 0x7) << (pointer_size << 3)
            pointer += _POINTER_VALUE_OFFSETS[pointer_size]
        pointer += self._pointer_base

        if self._pointer_test:
            return pointer, new_offset

        # The value at the pointer's position was charged by its containing
        # array or map, so the target costs nothing more. Only the depth changes.
        depth = budget[1] + 1
        if depth > _MAX_DEPTH:
            raise InvalidDatabaseError(_TOO_DEEP)
        budget[1] = depth
        (value, _) = self._decode(pointer, budget, True)  # noqa: FBT003
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

    def decode(self, offset: int) -> tuple[Record, int]:
        """Decode a section of the data section starting at offset.

        Arguments:
            offset: the location of the data structure to decode

        """
        # The call-local budget holds values remaining, current depth, and
        # string and bytes payload remaining. Recursive calls share it, while
        # concurrent reads each get their own budget. Charge the root here.
        try:
            return self._decode(
                offset,
                [_MAX_VALUES - 1, 0, _MAX_PAYLOAD_BYTES],
                False,  # noqa: FBT003
            )
        except RecursionError as ex:
            raise InvalidDatabaseError(_TOO_DEEP) from ex
        except (IndexError, struct.error) as ex:
            # Convert failed buffer indexing and fixed-width unpacking.
            raise InvalidDatabaseError(_BAD_DATA) from ex

    # Keep type dispatch inline to avoid another call for every decoded value.
    # The positional booleans are intentional: keywords and omitted defaults
    # prevented CPython from using its fastest call path in our benchmarks.
    # pointer_target rejects pointers to other pointers.
    def _decode(  # noqa: C901, PLR0911, PLR0912
        self,
        offset: int,
        budget: list[int],
        pointer_target: bool,  # noqa: FBT001
    ) -> tuple[Record, int]:
        new_offset = offset + 1
        ctrl_byte = self._buffer[offset]
        type_num = ctrl_byte >> 5
        # Extended type
        if not type_num:
            (type_num, new_offset) = self._read_extended(new_offset)

        size = ctrl_byte & 0x1F
        # Sizes under 29 are stored in the ctrl byte, and a pointer's size bits
        # are not a size. Skip the call for that common case.
        if size >= 29 and type_num != 1:
            (size, new_offset) = self._size_from_ctrl_byte(size, new_offset)
        # Put common types first to reduce comparisons during real lookups.
        match type_num:
            case 2:
                # Strings are most of the values in a real database. Decode them
                # here to save a method call.
                # Charge the payload before copying so a crafted size cannot force
                # a large allocation, and so pointers reusing one target recharge.
                remaining = budget[2] - size
                if remaining < 0:
                    raise InvalidDatabaseError(_TOO_LARGE)
                budget[2] = remaining
                end = new_offset + size
                return self._buffer[new_offset:end].decode("utf-8"), end
            case 1:
                if pointer_target:
                    raise InvalidDatabaseError(_BAD_DATA)
                return self._decode_pointer(size, new_offset, budget)
            case 7:
                return self._decode_map(size, new_offset, budget)
            case 6 | 5 | 9 | 10:  # uint32, uint16, uint64, uint128
                return self._decode_uint(size, new_offset, budget)
            case 11:
                return self._decode_array(size, new_offset, budget)
            case 3:
                return self._decode_double(size, new_offset, budget)
            case 4:
                return self._decode_bytes(size, new_offset, budget)
            case 8:
                return self._decode_int32(size, new_offset, budget)
            case 14:
                return self._decode_boolean(size, new_offset, budget)
            case 15:
                return self._decode_float(size, new_offset, budget)
            case _:
                msg = f"Unexpected type number ({type_num}) encountered"
                raise InvalidDatabaseError(msg)

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
