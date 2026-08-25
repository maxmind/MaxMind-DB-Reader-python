from __future__ import annotations

import mmap
import sys
import threading
import unittest
from typing import TYPE_CHECKING, Any, ClassVar, SupportsIndex

from maxminddb.decoder import Decoder
from maxminddb.errors import InvalidDatabaseError

if TYPE_CHECKING:
    from _typeshed import SizedBuffer
    from typing_extensions import Self

# Each structural level uses about two Python frames. This lets the 513-level
# cases reach the decoder's explicit limit with ample test-harness headroom.
_DEPTH_TEST_RECURSION_LIMIT = 2_000

_TOO_MANY_VALUES = (
    "^The MaxMind DB file's data section exceeds the maximum number of values$"
)
_TOO_DEEP = "^The MaxMind DB file's data section exceeds the maximum depth$"


class _HeaderOnlyBuffer(bytes):
    """A buffer that fails any read past its first ``header_len`` bytes.

    It proves that a check runs before the decoder touches child or payload
    bytes, rather than only that the check eventually fires.
    """

    header_len: int

    def __new__(cls, data: bytes, header_len: int) -> Self:
        buf = super().__new__(cls, data)
        buf.header_len = header_len
        return buf

    def __getitem__(self, index: SupportsIndex | slice) -> int | bytes:  # type: ignore[override]
        stop = index.stop if isinstance(index, slice) else int(index) + 1
        if stop > self.header_len:
            msg = f"decoder read past the {self.header_len}-byte header"
            raise AssertionError(msg)
        return bytes.__getitem__(self, index)


class TestDecoder(unittest.TestCase):
    def test_arrays(self) -> None:
        arrays = {
            b"\x00\x04": [],
            b"\x01\x04\x43\x46\x6f\x6f": ["Foo"],
            b"\x02\x04\x43\x46\x6f\x6f\x43\xe4\xba\xba": ["Foo", "人"],
        }
        self.validate_type_decoding("arrays", arrays)

    def test_boolean(self) -> None:
        booleans = {
            b"\x00\x07": False,
            b"\x01\x07": True,
        }
        self.validate_type_decoding("booleans", booleans)

    def test_double(self) -> None:
        doubles = {
            b"\x68\x00\x00\x00\x00\x00\x00\x00\x00": 0.0,
            b"\x68\x3f\xe0\x00\x00\x00\x00\x00\x00": 0.5,
            b"\x68\x40\x09\x21\xfb\x54\x44\x2e\xea": 3.14159265359,
            b"\x68\x40\x5e\xc0\x00\x00\x00\x00\x00": 123.0,
            b"\x68\x41\xd0\x00\x00\x00\x07\xf8\xf4": 1073741824.12457,
            b"\x68\xbf\xe0\x00\x00\x00\x00\x00\x00": -0.5,
            b"\x68\xc0\x09\x21\xfb\x54\x44\x2e\xea": -3.14159265359,
            b"\x68\xc1\xd0\x00\x00\x00\x07\xf8\xf4": -1073741824.12457,
        }
        self.validate_type_decoding("double", doubles)

    def test_float(self) -> None:
        floats = {
            b"\x04\x08\x00\x00\x00\x00": 0.0,
            b"\x04\x08\x3f\x80\x00\x00": 1.0,
            b"\x04\x08\x3f\x8c\xcc\xcd": 1.1,
            b"\x04\x08\x40\x48\xf5\xc3": 3.14,
            b"\x04\x08\x46\x1c\x3f\xf6": 9999.99,
            b"\x04\x08\xbf\x80\x00\x00": -1.0,
            b"\x04\x08\xbf\x8c\xcc\xcd": -1.1,
            b"\x04\x08\xc0\x48\xf5\xc3": -3.14,
            b"\x04\x08\xc6\x1c\x3f\xf6": -9999.99,
        }
        self.validate_type_decoding("float", floats)

    def test_int32(self) -> None:
        int32 = {
            b"\x00\x01": 0,
            b"\x04\x01\xff\xff\xff\xff": -1,
            b"\x01\x01\xff": 255,
            b"\x04\x01\xff\xff\xff\x01": -255,
            b"\x02\x01\x01\xf4": 500,
            b"\x04\x01\xff\xff\xfe\x0c": -500,
            b"\x02\x01\xff\xff": 65535,
            b"\x04\x01\xff\xff\x00\x01": -65535,
            b"\x03\x01\xff\xff\xff": 16777215,
            b"\x04\x01\xff\x00\x00\x01": -16777215,
            b"\x04\x01\x7f\xff\xff\xff": 2147483647,
            b"\x04\x01\x80\x00\x00\x01": -2147483647,
        }
        self.validate_type_decoding("int32", int32)

    def test_map(self) -> None:
        maps = {
            b"\xe0": {},
            b"\xe1\x42\x65\x6e\x43\x46\x6f\x6f": {"en": "Foo"},
            b"\xe2\x42\x65\x6e\x43\x46\x6f\x6f\x42\x7a\x68\x43\xe4\xba\xba": {
                "en": "Foo",
                "zh": "人",
            },
            (
                b"\xe1\x44\x6e\x61\x6d\x65\xe2\x42\x65\x6e"
                b"\x43\x46\x6f\x6f\x42\x7a\x68\x43\xe4\xba\xba"
            ): {"name": {"en": "Foo", "zh": "人"}},
            (
                b"\xe1\x49\x6c\x61\x6e\x67\x75\x61\x67\x65\x73"
                b"\x02\x04\x42\x65\x6e\x42\x7a\x68"
            ): {"languages": ["en", "zh"]},
        }
        self.validate_type_decoding("maps", maps)

    def test_pointer(self) -> None:
        pointers = {
            b"\x20\x00": 0,
            b"\x20\x05": 5,
            b"\x20\x0a": 10,
            b"\x23\xff": 1023,
            b"\x28\x03\xc9": 3017,
            b"\x2f\xf7\xfb": 524283,
            b"\x2f\xff\xff": 526335,
            b"\x37\xf7\xf7\xfe": 134217726,
            b"\x37\xff\xff\xff": 134744063,
            b"\x38\x7f\xff\xff\xff": 2147483647,
            b"\x38\xff\xff\xff\xff": 4294967295,
        }
        self.validate_type_decoding("pointers", pointers)

    strings: ClassVar = {
        b"\x40": "",
        b"\x41\x31": "1",
        b"\x43\xe4\xba\xba": "人",
        (
            b"\x5b\x31\x32\x33\x34"
            b"\x35\x36\x37\x38\x39\x30\x31\x32\x33\x34\x35"
            b"\x36\x37\x38\x39\x30\x31\x32\x33\x34\x35\x36\x37"
        ): "123456789012345678901234567",
        (
            b"\x5c\x31\x32\x33\x34"
            b"\x35\x36\x37\x38\x39\x30\x31\x32\x33\x34\x35"
            b"\x36\x37\x38\x39\x30\x31\x32\x33\x34\x35\x36"
            b"\x37\x38"
        ): "1234567890123456789012345678",
        (
            b"\x5d\x00\x31\x32\x33"
            b"\x34\x35\x36\x37\x38\x39\x30\x31\x32\x33\x34"
            b"\x35\x36\x37\x38\x39\x30\x31\x32\x33\x34\x35"
            b"\x36\x37\x38\x39"
        ): "12345678901234567890123456789",
        (
            b"\x5d\x01\x31\x32\x33"
            b"\x34\x35\x36\x37\x38\x39\x30\x31\x32\x33\x34"
            b"\x35\x36\x37\x38\x39\x30\x31\x32\x33\x34\x35"
            b"\x36\x37\x38\x39\x30"
        ): "123456789012345678901234567890",
        b"\x5e\x00\xd7" + 500 * b"\x78": "x" * 500,
        b"\x5e\x06\xb3" + 2000 * b"\x78": "x" * 2000,
        b"\x5f\x00\x10\x53" + 70000 * b"\x78": "x" * 70000,
    }

    def test_string(self) -> None:
        self.validate_type_decoding("string", self.strings)

    def test_byte(self) -> None:
        b = {
            bytes([0xC0 ^ k[0]]) + k[1:]: v.encode("utf-8")
            for k, v in self.strings.items()
        }
        self.validate_type_decoding("byte", b)

    def test_uint16(self) -> None:
        uint16 = {
            b"\xa0": 0,
            b"\xa1\xff": 255,
            b"\xa2\x01\xf4": 500,
            b"\xa2\x2a\x78": 10872,
            b"\xa2\xff\xff": 65535,
        }
        self.validate_type_decoding("uint16", uint16)

    def test_uint32(self) -> None:
        uint32 = {
            b"\xc0": 0,
            b"\xc1\xff": 255,
            b"\xc2\x01\xf4": 500,
            b"\xc2\x2a\x78": 10872,
            b"\xc2\xff\xff": 65535,
            b"\xc3\xff\xff\xff": 16777215,
            b"\xc4\xff\xff\xff\xff": 4294967295,
        }
        self.validate_type_decoding("uint32", uint32)

    def generate_large_uint(self, bits: int) -> dict:
        ctrl_byte = b"\x02" if bits == 64 else b"\x03"
        uints = {
            b"\x00" + ctrl_byte: 0,
            b"\x02" + ctrl_byte + b"\x01\xf4": 500,
            b"\x02" + ctrl_byte + b"\x2a\x78": 10872,
        }
        for power in range(bits // 8 + 1):
            expected = 2 ** (8 * power) - 1
            input_value = bytes([power]) + ctrl_byte + (b"\xff" * power)
            uints[input_value] = expected
        return uints

    def test_uint64(self) -> None:
        self.validate_type_decoding("uint64", self.generate_large_uint(64))

    def test_uint128(self) -> None:
        self.validate_type_decoding("uint128", self.generate_large_uint(128))

    def validate_type_decoding(self, data_type: str, tests: dict) -> None:
        for input_value, expected in tests.items():
            self.check_decoding(data_type, input_value, expected)

    def check_decoding(
        self,
        data_type: str,
        input_value: SizedBuffer,
        expected: Any,  # noqa: ANN401
        name: str | None = None,
    ) -> None:
        name = name or expected
        db = mmap.mmap(-1, len(input_value))
        db.write(input_value)

        decoder = Decoder(db, pointer_test=True)
        (
            actual,
            _,
        ) = decoder.decode(0)

        if data_type in ("float", "double"):
            self.assertAlmostEqual(expected, actual, places=3, msg=data_type)
        else:
            self.assertEqual(expected, actual, data_type)

    def test_real_pointers(self) -> None:
        with open("tests/data/test-data/maps-with-pointers.raw", "r+b") as db_file:
            mm = mmap.mmap(db_file.fileno(), 0)
            decoder = Decoder(mm, 0)

            self.assertEqual(({"long_key": "long_value1"}, 22), decoder.decode(0))

            self.assertEqual(({"long_key": "long_value2"}, 37), decoder.decode(22))

            self.assertEqual(({"long_key2": "long_value1"}, 50), decoder.decode(37))

            self.assertEqual(({"long_key2": "long_value2"}, 55), decoder.decode(50))

            self.assertEqual(({"long_key": "long_value1"}, 57), decoder.decode(55))

            self.assertEqual(({"long_key2": "long_value2"}, 59), decoder.decode(57))

            mm.close()

    @staticmethod
    def _pointer(target: int) -> bytes:
        # One-byte-payload pointer (type 1, pointer_size 1) with base 0.
        return bytes([(1 << 5) | ((target >> 8) & 0x7), target & 0xFF])

    def test_pointer_fan_out_is_bounded(self) -> None:
        # A data section of nested arrays, each holding two pointers to the
        # node below, would cost 2**depth decode operations. The decoder bounds
        # the number of values it decodes per lookup and rejects the database.
        depth = 100
        buf = bytearray([0xA0])  # leaf: uint16 with value 0
        prev = 0
        for _ in range(depth):
            offset = len(buf)
            buf += bytes([0x02, 0x04]) + self._pointer(prev) + self._pointer(prev)
            prev = offset

        with self.assertRaises(InvalidDatabaseError):
            Decoder(bytes(buf), pointer_base=0).decode(prev)

    @classmethod
    def _scalar_pointer_array(cls, pointer_count: int) -> bytes:
        # A uint16 leaf at offset 0 and, at offset 1, an array of pointers to
        # it. 0x1e: extended type with size code 30; 0x04: array.
        header = bytes([0xA0, 0x1E, 0x04]) + (pointer_count - 285).to_bytes(2, "big")
        return header + cls._pointer(0) * pointer_count

    def test_value_limit_follows_the_flat_rule(self) -> None:
        # The specification charges the root as one value and each pointer as
        # the value it resolves to, not as a separate value. An array of 65,535
        # pointers to a scalar is therefore 65,536 values, exactly the limit,
        # and decodes. One more pointer exceeds it.
        (decoded, _) = Decoder(
            self._scalar_pointer_array(65_535), pointer_base=0
        ).decode(1)
        self.assertEqual(decoded, [0] * 65_535)

        with self.assertRaisesRegex(InvalidDatabaseError, _TOO_MANY_VALUES):
            Decoder(self._scalar_pointer_array(65_536), pointer_base=0).decode(1)

    def test_cyclic_pointer_raises(self) -> None:
        # A pointer to itself must hit the decoder's own depth limit even when
        # Python's process-wide recursion limit is much higher.
        cyclic = bytes([0x20, 0x00])  # pointer (base 0) to offset 0, itself
        old_recursion_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(_DEPTH_TEST_RECURSION_LIMIT)
            with self.assertRaisesRegex(InvalidDatabaseError, _TOO_DEEP):
                Decoder(cyclic, pointer_base=0).decode(0)
        finally:
            sys.setrecursionlimit(old_recursion_limit)

    def test_container_depth_is_bounded_independently_of_recursion_limit(self) -> None:
        # Each prefix is an array with one element. Raising Python's global
        # recursion limit proves that the decoder's call-local limit is what
        # accepts 512 containers and rejects the 513th.
        at_limit = bytes([0x01, 0x04]) * 512 + bytes([0xA0])
        over_limit = bytes([0x01, 0x04]) * 513 + bytes([0xA0])
        old_recursion_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(_DEPTH_TEST_RECURSION_LIMIT)
            Decoder(at_limit, pointer_base=0).decode(0)
            with self.assertRaisesRegex(InvalidDatabaseError, _TOO_DEEP):
                Decoder(over_limit, pointer_base=0).decode(0)
        finally:
            sys.setrecursionlimit(old_recursion_limit)

    @classmethod
    def _pointer_chain(cls, levels: int) -> tuple[bytes, int]:
        # Each level is a one-element array whose element is a pointer to the
        # level below, so each level costs two depth units: the array and the
        # pointer follow.
        buf = bytearray([0xA0])
        prev = 0
        for _ in range(levels):
            offset = len(buf)
            buf += bytes([0x01, 0x04]) + cls._pointer(prev)
            prev = offset
        return bytes(buf), prev

    def test_depth_counts_pointer_follows(self) -> None:
        # 256 array-plus-pointer levels are exactly 512 depth units and decode.
        # 257 exceed the limit through the decoder's own counter, not the
        # interpreter's, so the error has no RecursionError cause.
        old_recursion_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(_DEPTH_TEST_RECURSION_LIMIT)
            buf, start = self._pointer_chain(256)
            Decoder(buf, pointer_base=0).decode(start)
            buf, start = self._pointer_chain(257)
            with self.assertRaisesRegex(InvalidDatabaseError, _TOO_DEEP) as cm:
                Decoder(buf, pointer_base=0).decode(start)
            self.assertIsNone(cm.exception.__cause__)
        finally:
            sys.setrecursionlimit(old_recursion_limit)

    def test_budget_is_local_to_each_decode(self) -> None:
        # Decoding an at-limit value twice on one Decoder, and from several
        # threads at once, must succeed every time. A budget stored on the
        # decoder would drain after the first call.
        decoder = Decoder(self._scalar_pointer_array(65_535), pointer_base=0)
        expected = [0] * 65_535
        self.assertEqual(decoder.decode(1)[0], expected)
        self.assertEqual(decoder.decode(1)[0], expected)

        results: list[object] = []

        def run() -> None:
            results.append(decoder.decode(1)[0])

        threads = [threading.Thread(target=run) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results, [expected] * 8)

    def test_oversized_array_is_rejected_before_reading_children(self) -> None:
        # A root array that declares 65,536 elements is 65,537 values. The
        # buffer fails any read past the header, so the test proves the check
        # runs before the first element. 0x1e: extended type with size code
        # 30; 0x04: array; 0xfee3: 65,536 - 285.
        header = _HeaderOnlyBuffer(bytes([0x1E, 0x04, 0xFE, 0xE3]), 4)
        with self.assertRaisesRegex(InvalidDatabaseError, _TOO_MANY_VALUES):
            Decoder(header, pointer_base=0).decode(0)

    def test_oversized_map_is_rejected_before_reading_keys(self) -> None:
        # A map entry decodes a key and a value, so 32,769 entries cost 65,538
        # values, just past the limit. 0xfe: map with size code 30, then the
        # two size bytes for 32,769 - 285 = 32,484 (0x7ee4).
        header = _HeaderOnlyBuffer(bytes([0xFE, 0x7E, 0xE4]), 3)
        with self.assertRaisesRegex(InvalidDatabaseError, _TOO_MANY_VALUES):
            Decoder(header, pointer_base=0).decode(0)
