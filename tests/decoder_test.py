#!/usr/bin/env python

import mmap
import unittest

from maxminddb.decoder import Decoder


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

    strings = {
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

    def generate_large_uint(self, bits) -> dict:
        ctrl_byte = b"\x02" if bits == 64 else b"\x03"
        uints = {
            b"\x00" + ctrl_byte: 0,
            b"\x02" + ctrl_byte + b"\x01\xf4": 500,
            b"\x02" + ctrl_byte + b"\x2a\x78": 10872,
        }
        for power in range(bits // 8 + 1):
            expected = 2 ** (8 * power) - 1
            input = bytes([power]) + ctrl_byte + (b"\xff" * power)
            uints[input] = expected
        return uints

    def test_uint64(self) -> None:
        self.validate_type_decoding("uint64", self.generate_large_uint(64))

    def test_uint128(self) -> None:
        self.validate_type_decoding("uint128", self.generate_large_uint(128))

    def validate_type_decoding(self, type, tests) -> None:
        for input, expected in tests.items():
            self.check_decoding(type, input, expected)

    def check_decoding(self, type, input, expected, name=None) -> None:
        name = name or expected
        db = mmap.mmap(-1, len(input))
        db.write(input)

        decoder = Decoder(db, pointer_test=True)
        (
            actual,
            _,
        ) = decoder.decode(0)

        if type in ("float", "double"):
            self.assertAlmostEqual(expected, actual, places=3, msg=type)
        else:
            self.assertEqual(expected, actual, type)

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
