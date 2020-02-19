"""
maxminddb.decoder
~~~~~~~~~~~~~~~~~

This package contains code for decoding the MaxMind DB data section.

"""
from __future__ import unicode_literals

import struct

from maxminddb.compat import byte_from_int, int_from_byte, int_from_bytes
from maxminddb.errors import InvalidDatabaseError


class Decoder(object):  # pylint: disable=too-few-public-methods
    """Decoder for the data section of the MaxMind DB"""

    def __init__(self, database_buffer, pointer_base=0, pointer_test=False):
        """Created a Decoder for a MaxMind DB

        Arguments:
        database_buffer -- an mmap'd MaxMind DB file.
        pointer_base -- the base number to use when decoding a pointer
        pointer_test -- used for internal unit testing of pointer code
        """
        self._pointer_test = pointer_test
        self._buffer = database_buffer
        self._pointer_base = pointer_base

    def _decode_array(self, size, offset):
        array = []
        for _ in range(size):
            (value, offset) = self.decode(offset)
            array.append(value)
        return array, offset

    def _decode_boolean(self, size, offset):
        return size != 0, offset

    def _decode_bytes(self, size, offset):
        new_offset = offset + size
        return self._buffer[offset:new_offset], new_offset

    def _decode_double(self, size, offset):
        self._verify_size(size, 8)
        new_offset = offset + size
        packed_bytes = self._buffer[offset:new_offset]
        (value,) = struct.unpack(b"!d", packed_bytes)
        return value, new_offset

    def _decode_float(self, size, offset):
        self._verify_size(size, 4)
        new_offset = offset + size
        packed_bytes = self._buffer[offset:new_offset]
        (value,) = struct.unpack(b"!f", packed_bytes)
        return value, new_offset

    def _decode_int32(self, size, offset):
        if size == 0:
            return 0, offset
        new_offset = offset + size
        packed_bytes = self._buffer[offset:new_offset]

        if size != 4:
            packed_bytes = packed_bytes.rjust(4, b"\x00")
        (value,) = struct.unpack(b"!i", packed_bytes)
        return value, new_offset

    def _decode_map(self, size, offset):
        container = {}
        for _ in range(size):
            (key, offset) = self.decode(offset)
            (value, offset) = self.decode(offset)
            container[key] = value
        return container, offset

    def _decode_pointer(self, size, offset):
        pointer_size = (size >> 3) + 1

        buf = self._buffer[offset : offset + pointer_size]
        new_offset = offset + pointer_size

        if pointer_size == 1:
            buf = byte_from_int(size & 0x7) + buf
            pointer = struct.unpack(b"!H", buf)[0] + self._pointer_base
        elif pointer_size == 2:
            buf = b"\x00" + byte_from_int(size & 0x7) + buf
            pointer = struct.unpack(b"!I", buf)[0] + 2048 + self._pointer_base
        elif pointer_size == 3:
            buf = byte_from_int(size & 0x7) + buf
            pointer = struct.unpack(b"!I", buf)[0] + 526336 + self._pointer_base
        else:
            pointer = struct.unpack(b"!I", buf)[0] + self._pointer_base

        if self._pointer_test:
            return pointer, new_offset
        (value, _) = self.decode(pointer)
        return value, new_offset

    def _decode_uint(self, size, offset):
        new_offset = offset + size
        uint_bytes = self._buffer[offset:new_offset]
        return int_from_bytes(uint_bytes), new_offset

    def _decode_utf8_string(self, size, offset):
        new_offset = offset + size
        return self._buffer[offset:new_offset].decode("utf-8"), new_offset

    _type_decoder = {
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

    def decode(self, offset):
        """Decode a section of the data section starting at offset

        Arguments:
        offset -- the location of the data structure to decode
        """
        new_offset = offset + 1
        ctrl_byte = int_from_byte(self._buffer[offset])
        type_num = ctrl_byte >> 5
        # Extended type
        if not type_num:
            (type_num, new_offset) = self._read_extended(new_offset)

        try:
            decoder = self._type_decoder[type_num]
        except KeyError:
            raise InvalidDatabaseError(
                "Unexpected type number ({type}) " "encountered".format(type=type_num)
            )

        (size, new_offset) = self._size_from_ctrl_byte(ctrl_byte, new_offset, type_num)
        return decoder(self, size, new_offset)

    def _read_extended(self, offset):
        next_byte = int_from_byte(self._buffer[offset])
        type_num = next_byte + 7
        if type_num < 7:
            raise InvalidDatabaseError(
                "Something went horribly wrong in the decoder. An "
                "extended type resolved to a type number < 8 "
                "({type})".format(type=type_num)
            )
        return type_num, offset + 1

    def _verify_size(self, expected, actual):
        if expected != actual:
            raise InvalidDatabaseError(
                "The MaxMind DB file's data section contains bad data "
                "(unknown data type or corrupt data)"
            )

    def _size_from_ctrl_byte(self, ctrl_byte, offset, type_num):
        size = ctrl_byte & 0x1F
        if type_num == 1 or size < 29:
            return size, offset

        if size == 29:
            size = 29 + int_from_byte(self._buffer[offset])
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
