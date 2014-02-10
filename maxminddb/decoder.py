from __future__ import unicode_literals

from struct import pack, unpack

from .compat import byte_from_int, int_from_bytes
from .errors import InvalidDatabaseError


class Decoder(object):

    """Decodes the data section of the MaxMind DB"""

    def __init__(self, database_buffer, pointer_base=0, pointer_test=False):
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

    def _decode_packed_type(type_code, type_size, pad=False):
        def unpack_type(self, size, offset):
            if not pad:
                self._verify_size(size, type_size)
            new_offset = offset + type_size
            packed_bytes = self._buffer[offset:new_offset]
            if pad:
                packed_bytes = packed_bytes.rjust(type_size, b'\x00')
            (value,) = unpack(type_code, packed_bytes)
            return value, new_offset
        return unpack_type

    def _decode_map(self, size, offset):
        container = {}
        for _ in range(size):
            (key, offset) = self.decode(offset)
            (value, offset) = self.decode(offset)
            container[key] = value
        return container, offset

    _pointer_value_offset = {
        1: 0,
        2: 2048,
        3: 526336,
        4: 0,
    }

    def _decode_pointer(self, size, offset):
        pointer_size = ((size >> 3) & 0x3) + 1
        new_offset = offset + pointer_size
        b = self._buffer[offset:new_offset]
        packed = b if pointer_size == 4 else pack(
            b'!c', byte_from_int(size & 0x7)) + b
        unpacked = int_from_bytes(packed)
        pointer = unpacked + self._pointer_base + \
            self._pointer_value_offset[pointer_size]
        if self._pointer_test:
            return pointer, new_offset
        (value, _) = self.decode(pointer)
        return value, new_offset

    def _decode_uint(self, size, offset):
        new_offset = offset + size
        b = self._buffer[offset:new_offset]
        return int_from_bytes(b), new_offset

    def _decode_utf8_string(self, size, offset):
        new_offset = offset + size
        return self._buffer[offset:new_offset].decode('utf-8'), new_offset

    _type_dispatch = {
        1: _decode_pointer,
        2: _decode_utf8_string,
        3: _decode_packed_type(b'!d', 8),  # double,
        4: _decode_bytes,
        5: _decode_uint,  # uint16
        6: _decode_uint,  # uint32
        7: _decode_map,
        8: _decode_packed_type(b'!i', 4, pad=True),  # int32
        9: _decode_uint,  # uint64
        10: _decode_uint,  # uint128
        11: _decode_array,
        14: _decode_boolean,
        15: _decode_packed_type(b'!f', 4),  # float,
    }

    def decode(self, offset):
        new_offset = offset + 1
        (ctrl_byte,) = unpack(b'!B', self._buffer[offset:new_offset])
        type_num = ctrl_byte >> 5
        # Extended type
        if not type_num:
            (type_num, new_offset) = self._read_extended(new_offset)

        (size, new_offset) = self._size_from_ctrl_byte(
            ctrl_byte, new_offset, type_num)
        return self._type_dispatch[type_num](self, size, new_offset)

    def _read_extended(self, offset):
        (next_byte,) = unpack(b'!B', self._buffer[offset:offset + 1])
        type_num = next_byte + 7
        if type_num < 7:
            raise InvalidDatabaseError(
                'Something went horribly wrong in the decoder. An '
                'extended type resolved to a type number < 8 '
                '({type})'.format(type=type_num))
        return next_byte + 7, offset + 1

    def _verify_size(self, expected, actual):
        if expected != actual:
            raise InvalidDatabaseError(
                'The MaxMind DB file\'s data section contains bad data '
                '(unknown data type or corrupt data)'
            )

    def _size_from_ctrl_byte(self, ctrl_byte, offset, type_num):
        size = ctrl_byte & 0x1f
        if type_num == 1:
            return size, offset
        bytes_to_read = 0 if size < 29 else size - 28
        size_bytes = self._buffer[offset:offset + bytes_to_read]

        # Using unpack rather than int_from_bytes as it is about 200 lookups
        # per second faster here.
        if size == 29:
            size = 29 + unpack(b'!B', size_bytes)[0]
        elif size == 30:
            size = 285 + unpack(b'!H', size_bytes)[0]
        elif size > 30:
            size = unpack(b'!I', size_bytes.rjust(4, b'\x00'))[0] + 65821

        return size, offset + bytes_to_read