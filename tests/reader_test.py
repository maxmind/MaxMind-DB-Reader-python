from __future__ import annotations

import contextlib
import gc
import io
import ipaddress
import mmap
import multiprocessing
import os
import pathlib
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import threading
import tracemalloc
import unittest
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

import maxminddb

try:
    import maxminddb.extension
except ImportError:
    maxminddb.extension = None  # type: ignore[assignment]

from maxminddb import InvalidDatabaseError, open_database
from maxminddb.const import (
    MODE_AUTO,
    MODE_FD,
    MODE_FILE,
    MODE_MEMORY,
    MODE_MMAP,
    MODE_MMAP_EXT,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from maxminddb.reader import Reader


# Directory holding the shared MaxMind DB test fixtures.
_TEST_DATA_DIR = "tests/data/test-data"
_DECODER_DB = f"{_TEST_DATA_DIR}/MaxMind-DB-test-decoder.mmdb"
# Valid arguments for the C extension Metadata.
_METADATA_FIELDS: dict[str, Any] = {
    "binary_format_major_version": 2,
    "binary_format_minor_version": 0,
    "build_epoch": 1,
    "database_type": "db",
    "description": {},
    "ip_version": 4,
    "languages": [],
    "node_count": 1,
    "record_size": 24,
}
_PAYLOAD_TOO_LARGE = (
    "^The MaxMind DB file's data section exceeds the maximum payload size$"
)
_TOO_MANY_VALUES = (
    "^The MaxMind DB file's data section exceeds the maximum number of values$"
)
_TOO_DEEP = "^The MaxMind DB file's data section exceeds the maximum depth$"
_EXTENSION_LIMIT_MESSAGE = "exceeds the configured resource limits"


@contextlib.contextmanager
def _bounded(seconds: int = 60, address_space: int = 2 << 30) -> Iterator[None]:
    """Fail, rather than hang or exhaust memory, if a limit regresses.

    POSIX only. macOS refuses to lower RLIMIT_AS, and a process that already
    uses more address space than the cap, such as one under AddressSanitizer,
    would die on its next allocation; only the alarm applies in those cases.
    """
    if sys.platform == "win32":
        yield
        return
    import resource  # noqa: PLC0415
    import signal  # noqa: PLC0415

    def on_alarm(*_: object) -> None:
        msg = f"hostile decode did not stop within {seconds}s"
        raise TimeoutError(msg)

    def address_space_in_use() -> int:
        # Linux only; elsewhere the size is unknown and the cap applies.
        try:
            with open("/proc/self/statm") as statm:
                return int(statm.read().split()[0]) * resource.getpagesize()
        except (OSError, ValueError):
            return 0

    cap_memory = sys.platform != "darwin" and address_space_in_use() < address_space
    if cap_memory:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        limit = (
            address_space
            if hard == resource.RLIM_INFINITY
            else min(address_space, hard)
        )
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    old_handler = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        if cap_memory:
            resource.setrlimit(resource.RLIMIT_AS, (soft, hard))


def get_reader_from_file_descriptor(filepath: str, mode: int) -> Reader:
    """Patches open_database() for class TestFDReader()."""
    if mode == MODE_FD:
        with open(filepath, "rb") as mmdb_fh:
            return maxminddb.open_database(mmdb_fh, mode)
    else:
        # There are a few cases where mode is statically defined in
        # BaseTestReader(). In those cases just call an unpatched
        # open_database() with a string path.
        return maxminddb.open_database(filepath, mode)


class BaseTestReader(unittest.TestCase):
    mode: int
    reader_class: type[maxminddb.extension.Reader | maxminddb.reader.Reader]
    use_ip_objects = False
    payload_error = _PAYLOAD_TOO_LARGE
    value_count_error = _TOO_MANY_VALUES
    metadata_error = _PAYLOAD_TOO_LARGE
    fan_out_error = f"{_TOO_MANY_VALUES}|{_TOO_DEEP}"

    # fork doesn't work on Windows and spawn would involve pickling the reader,
    # which isn't possible.
    if os.name != "nt":
        mp = multiprocessing.get_context("fork")

    def ipf(self, ip: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | str:
        if self.use_ip_objects:
            return ipaddress.ip_address(ip)
        return ip

    def _require_resource_limits(self) -> None:
        # Only resource-limit tests call this, so older system libraries still
        # run the other reader tests. reader_class also handles MODE_AUTO.
        if self.reader_class is maxminddb.reader.Reader:
            return
        self.payload_error = _EXTENSION_LIMIT_MESSAGE
        self.value_count_error = _EXTENSION_LIMIT_MESSAGE
        self.fan_out_error = _EXTENSION_LIMIT_MESSAGE
        # libmaxminddb reports metadata rejection as a generic open failure.
        self.metadata_error = "Error opening"

        # Probe with a fixture one byte over the 2 MiB payload limit, which is
        # small and safe to decode even without the limits. The bundled
        # libmaxminddb has them, so it must reject the probe with the
        # decoder-limit message; anything else is a failure. A system library
        # selected with MAXMINDDB_USE_SYSTEM_LIBMAXMINDDB may predate the
        # limits and decode the probe. Skip then, rather than run the large
        # DoS fixtures through a decoder that would exhaust memory.
        try:
            self._lookup_resource_record(
                "MaxMind-DB-test-decoder-payload-limit-over.mmdb"
            )
        except InvalidDatabaseError as exc:
            if _EXTENSION_LIMIT_MESSAGE in str(exc):
                return
            raise
        if not os.environ.get("MAXMINDDB_USE_SYSTEM_LIBMAXMINDDB"):
            self.fail(
                "the bundled libmaxminddb decoded a record over the payload limit"
            )
        self.skipTest(
            "system libmaxminddb predates the decoder resource limits "
            "(needs the release that adds MMDB_DECODER_LIMIT_ERROR)",
        )

    def _lookup_resource_record(self, filename: str, ip: str = "0.0.0.1") -> object:
        # Each DoS fixture resolves any address to its single crafted record.
        with open_database(f"{_TEST_DATA_DIR}/{filename}", self.mode) as reader:
            return reader.get(self.ipf(ip))

    def test_payload_amplification_is_rejected(self) -> None:
        self._require_resource_limits()
        # An array of 8,192 pointers to one 65,535-byte value. The value count
        # stays low, but copying each target would materialize about 512 MiB.
        with (
            _bounded(),
            self.assertRaisesRegex(InvalidDatabaseError, self.payload_error),
        ):
            self._lookup_resource_record(
                "MaxMind-DB-test-payload-amplification-dos.mmdb"
            )

    def test_payload_amplification_string_is_rejected(self) -> None:
        self._require_resource_limits()
        # The UTF-8 string variant, so the decode path for strings is exercised.
        with (
            _bounded(),
            self.assertRaisesRegex(InvalidDatabaseError, self.payload_error),
        ):
            self._lookup_resource_record(
                "MaxMind-DB-test-payload-amplification-dos-string.mmdb"
            )

    def test_payload_amplification_worst_case_is_rejected(self) -> None:
        self._require_resource_limits()
        # 65,535 pointers to one 65,535-byte value. The record is exactly
        # 65,536 values under the flat rule, so only the payload budget can
        # reject it.
        with (
            _bounded(),
            self.assertRaisesRegex(InvalidDatabaseError, self.payload_error),
        ):
            self._lookup_resource_record(
                "MaxMind-DB-test-payload-amplification-dos-worst-case.mmdb"
            )

    def test_value_count_boundary(self) -> None:
        self._require_resource_limits()
        # The at-limit fixture decodes to exactly 65,536 values and must decode.
        # The pointer-heavy fixture reaches 65,535 values through pointers,
        # which cost nothing beyond the values they resolve to. One value more
        # than the limit is rejected.
        self.assertIsInstance(
            self._lookup_resource_record("MaxMind-DB-test-decoder-value-limit.mmdb"),
            list,
        )
        self.assertIsInstance(
            self._lookup_resource_record(
                "MaxMind-DB-test-decoder-value-limit-pointer-heavy.mmdb"
            ),
            list,
        )
        with self.assertRaisesRegex(InvalidDatabaseError, self.value_count_error):
            self._lookup_resource_record(
                "MaxMind-DB-test-decoder-value-limit-over.mmdb"
            )

    def test_pointer_fan_out_fixture_is_rejected(self) -> None:
        self._require_resource_limits()
        # A full database whose record nests arrays of pointers to the level
        # below, the classic 2**depth fan-out.
        with (
            _bounded(),
            self.assertRaisesRegex(InvalidDatabaseError, self.fan_out_error),
        ):
            self._lookup_resource_record("MaxMind-DB-test-pointer-decoder-dos.mmdb")

    def test_pointer_fan_out_ipv6_fixture_is_rejected(self) -> None:
        self._require_resource_limits()
        # The same fan-out in a conventional IPv6 database that maps the whole
        # address space to the record, so the IPv6 tree path is covered too.
        with (
            _bounded(),
            self.assertRaisesRegex(InvalidDatabaseError, self.fan_out_error),
        ):
            self._lookup_resource_record(
                "MaxMind-DB-test-pointer-decoder-dos-ipv6.mmdb", "2001:db8::1"
            )

    def test_payload_at_limit_is_accepted(self) -> None:
        self._require_resource_limits()
        # References totaling exactly 2 MiB of payload decode successfully, so
        # the limit does not reject a record at the boundary.
        self.assertIsInstance(
            self._lookup_resource_record("MaxMind-DB-test-decoder-payload-limit.mmdb"),
            list,
        )

    def test_payload_one_over_limit_is_rejected(self) -> None:
        self._require_resource_limits()
        # One byte more than 2 MiB is rejected, catching an off-by-one.
        with self.assertRaisesRegex(InvalidDatabaseError, self.payload_error):
            self._lookup_resource_record(
                "MaxMind-DB-test-decoder-payload-limit-over.mmdb"
            )

    def test_metadata_payload_limit_is_enforced_on_open(self) -> None:
        self._require_resource_limits()
        # Metadata must stay within the payload limit when the database is opened.
        with (
            _bounded(),
            self.assertRaisesRegex(InvalidDatabaseError, self.metadata_error),
            open_database(
                f"{_TEST_DATA_DIR}/MaxMind-DB-test-metadata-payload-limit.mmdb",
                self.mode,
            ),
        ):
            pass

    def test_normal_record_still_decodes(self) -> None:
        self._require_resource_limits()
        # A record with ordinary string and bytes values, which the payload
        # budget also charges, decodes unchanged.
        record = cast(
            "dict",
            self._lookup_resource_record("MaxMind-DB-test-decoder.mmdb", "::1.1.1.0"),
        )
        self.assertEqual(record["utf8_string"], "unicode! ☯ - ♫")
        self.assertEqual(record["bytes"], b"\x00\x00\x00*")

    def test_reader(self) -> None:
        for record_size in [24, 28, 32]:
            for ip_version in [4, 6]:
                file_name = (
                    "tests/data/test-data/MaxMind-DB-test-ipv"
                    + str(ip_version)
                    + "-"
                    + str(record_size)
                    + ".mmdb"
                )
                reader = open_database(file_name, self.mode)

                self._check_metadata(reader, ip_version, record_size)

                if ip_version == 4:
                    self._check_ip_v4(reader, file_name)
                else:
                    self._check_ip_v6(reader, file_name)
                reader.close()

    def test_get_with_prefix_len(self) -> None:
        decoder_record = {
            "array": [1, 2, 3],
            "boolean": True,
            "bytes": b"\x00\x00\x00*",
            "double": 42.123456,
            "float": 1.100000023841858,
            "int32": -268435456,
            "map": {
                "mapX": {
                    "arrayX": [7, 8, 9],
                    "utf8_stringX": "hello",
                },
            },
            "uint128": 1329227995784915872903807060280344576,
            "uint16": 0x64,
            "uint32": 0x10000000,
            "uint64": 0x1000000000000000,
            "utf8_string": "unicode! ☯ - ♫",
        }

        tests = [
            {
                "ip": "1.1.1.1",
                "file_name": "MaxMind-DB-test-ipv6-32.mmdb",
                "expected_prefix_len": 8,
                "expected_record": None,
            },
            {
                "ip": "::1:ffff:ffff",
                "file_name": "MaxMind-DB-test-ipv6-24.mmdb",
                "expected_prefix_len": 128,
                "expected_record": {"ip": "::1:ffff:ffff"},
            },
            {
                "ip": "::2:0:1",
                "file_name": "MaxMind-DB-test-ipv6-24.mmdb",
                "expected_prefix_len": 122,
                "expected_record": {"ip": "::2:0:0"},
            },
            {
                "ip": "1.1.1.1",
                "file_name": "MaxMind-DB-test-ipv4-24.mmdb",
                "expected_prefix_len": 32,
                "expected_record": {"ip": "1.1.1.1"},
            },
            {
                "ip": "1.1.1.3",
                "file_name": "MaxMind-DB-test-ipv4-24.mmdb",
                "expected_prefix_len": 31,
                "expected_record": {"ip": "1.1.1.2"},
            },
            {
                "ip": "1.1.1.3",
                "file_name": "MaxMind-DB-test-decoder.mmdb",
                "expected_prefix_len": 24,
                "expected_record": decoder_record,
            },
            {
                "ip": "::ffff:1.1.1.128",
                "file_name": "MaxMind-DB-test-decoder.mmdb",
                "expected_prefix_len": 120,
                "expected_record": decoder_record,
            },
            {
                "ip": "::1.1.1.128",
                "file_name": "MaxMind-DB-test-decoder.mmdb",
                "expected_prefix_len": 120,
                "expected_record": decoder_record,
            },
            {
                "ip": "200.0.2.1",
                "file_name": "MaxMind-DB-no-ipv4-search-tree.mmdb",
                "expected_prefix_len": 0,
                "expected_record": "::/64",
            },
            {
                "ip": "::200.0.2.1",
                "file_name": "MaxMind-DB-no-ipv4-search-tree.mmdb",
                "expected_prefix_len": 64,
                "expected_record": "::/64",
            },
            {
                "ip": "0:0:0:0:ffff:ffff:ffff:ffff",
                "file_name": "MaxMind-DB-no-ipv4-search-tree.mmdb",
                "expected_prefix_len": 64,
                "expected_record": "::/64",
            },
            {
                "ip": "ef00::",
                "file_name": "MaxMind-DB-no-ipv4-search-tree.mmdb",
                "expected_prefix_len": 1,
                "expected_record": None,
            },
        ]

        for test in tests:
            with open_database(
                "tests/data/test-data/" + cast("str", test["file_name"]),
                self.mode,
            ) as reader:
                (record, prefix_len) = reader.get_with_prefix_len(
                    cast("str", test["ip"]),
                )

                self.assertEqual(
                    prefix_len,
                    test["expected_prefix_len"],
                    f"expected prefix_len of {test['expected_prefix_len']}"
                    f" for {test['ip']}"
                    f" in {test['file_name']} but got {prefix_len}",
                )
                self.assertEqual(
                    record,
                    test["expected_record"],
                    "expected_record for "
                    + cast("str", test["ip"])
                    + " in "
                    + cast("str", test["file_name"]),
                )

    def test_iterator(self) -> None:
        tests = (
            {
                "database": "ipv4",
                "expected": [
                    "1.1.1.1/32",
                    "1.1.1.2/31",
                    "1.1.1.4/30",
                    "1.1.1.8/29",
                    "1.1.1.16/28",
                    "1.1.1.32/32",
                ],
            },
            {
                "database": "ipv6",
                "expected": [
                    "::1:ffff:ffff/128",
                    "::2:0:0/122",
                    "::2:0:40/124",
                    "::2:0:50/125",
                    "::2:0:58/127",
                ],
            },
            {
                "database": "mixed",
                "expected": [
                    "1.1.1.1/32",
                    "1.1.1.2/31",
                    "1.1.1.4/30",
                    "1.1.1.8/29",
                    "1.1.1.16/28",
                    "1.1.1.32/32",
                    "::1:ffff:ffff/128",
                    "::2:0:0/122",
                    "::2:0:40/124",
                    "::2:0:50/125",
                    "::2:0:58/127",
                ],
            },
        )

        for record_size in [24, 28, 32]:
            for test in tests:
                f = (
                    f"tests/data/test-data/MaxMind-DB-test-{test['database']}"
                    f"-{record_size}.mmdb"
                )
                reader = open_database(f, self.mode)
                networks = [str(n) for (n, _) in reader]
                self.assertEqual(networks, test["expected"], f)

    def test_decoder(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        record = cast("dict", reader.get(self.ipf("::1.1.1.0")))

        self.assertEqual(record["array"], [1, 2, 3])
        self.assertEqual(record["boolean"], True)
        self.assertEqual(record["bytes"], bytearray(b"\x00\x00\x00*"))
        self.assertEqual(record["double"], 42.123456)
        self.assertAlmostEqual(record["float"], 1.1)
        self.assertEqual(record["int32"], -268435456)
        self.assertEqual(
            {
                "mapX": {"arrayX": [7, 8, 9], "utf8_stringX": "hello"},
            },
            record["map"],
        )

        self.assertEqual(record["uint16"], 100)
        self.assertEqual(record["uint32"], 268435456)
        self.assertEqual(record["uint64"], 1152921504606846976)
        self.assertEqual(record["utf8_string"], "unicode! ☯ - ♫")

        self.assertEqual(1329227995784915872903807060280344576, record["uint128"])
        reader.close()

    def test_decoder_maximum_values(self) -> None:
        with open_database(_DECODER_DB, self.mode) as reader:
            record = cast("dict", reader.get(self.ipf("::255.255.255.255")))
        # A C long has 32 bits on Windows, where a signed conversion would make
        # the uint32 negative.
        self.assertEqual(record["uint32"], 2**32 - 1)
        self.assertEqual(record["uint64"], 2**64 - 1)
        self.assertEqual(record["uint128"], 2**128 - 1)

    def test_metadata_pointers(self) -> None:
        with open_database(
            "tests/data/test-data/MaxMind-DB-test-metadata-pointers.mmdb",
            self.mode,
        ) as reader:
            self.assertEqual(
                "Lots of pointers in metadata",
                reader.metadata().database_type,
            )

    def test_no_ipv4_search_tree(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-no-ipv4-search-tree.mmdb",
            self.mode,
        )

        self.assertEqual(reader.get(self.ipf("1.1.1.1")), "::/64")
        self.assertEqual(reader.get(self.ipf("192.1.1.1")), "::/64")
        reader.close()

    def test_ipv6_address_in_ipv4_database(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb",
            self.mode,
        )
        with self.assertRaisesRegex(
            ValueError,
            "Error looking up 2001::. "
            "You attempted to look up an IPv6 address "
            "in an IPv4-only database",
        ):
            reader.get(self.ipf("2001::"))
        reader.close()

    def test_opening_path(self) -> None:
        with open_database(
            pathlib.Path("tests/data/test-data/MaxMind-DB-test-decoder.mmdb"),
            self.mode,
        ) as reader:
            self.assertEqual(reader.metadata().database_type, "MaxMind DB Decoder Test")

    def test_no_extension_exception(self) -> None:
        real_extension = maxminddb._extension  # noqa: SLF001
        maxminddb._extension = None  # type: ignore[assignment]  # noqa: SLF001
        with self.assertRaisesRegex(
            ValueError,
            "MODE_MMAP_EXT requires the maxminddb.extension module to be available",
        ):
            open_database(
                "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
                MODE_MMAP_EXT,
            )
        maxminddb._extension = real_extension  # noqa: SLF001

    def test_broken_database(self) -> None:
        reader = open_database(
            "tests/data/test-data/GeoIP2-City-Test-Broken-Double-Format.mmdb",
            self.mode,
        )
        with self.assertRaisesRegex(
            InvalidDatabaseError,
            r"The MaxMind DB file's data "
            r"section contains bad data \(unknown data "
            r"type or corrupt data\)",
        ):
            reader.get(self.ipf("2001:220::"))
        reader.close()

    def test_search_tree_past_end_of_file(self) -> None:
        # The metadata claims more nodes than the file holds. The pure Python
        # reader rejects this when the database is opened; libmaxminddb does
        # the same or fails the first lookup.
        if self.reader_class is maxminddb.reader.Reader:
            with (
                self.assertRaisesRegex(
                    InvalidDatabaseError,
                    "The search tree extends past the end of the file",
                ),
                open_database(
                    f"{_TEST_DATA_DIR}/GeoIP2-City-Test-Invalid-Node-Count.mmdb",
                    self.mode,
                ),
            ):
                pass
            return
        with (
            self.assertRaises(InvalidDatabaseError),
            open_database(
                "tests/data/test-data/GeoIP2-City-Test-Invalid-Node-Count.mmdb",
                self.mode,
            ) as reader,
        ):
            reader.get(self.ipf("1.1.1.1"))

    def test_ip_validation(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        with self.assertRaisesRegex(
            ValueError,
            "'not_ip' does not appear to be an IPv4 or IPv6 address",
        ):
            reader.get("not_ip")
        reader.close()

    def test_missing_database(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "No such file or directory"):
            open_database("file-does-not-exist.mmdb", self.mode)

    def test_nondatabase(self) -> None:
        with self.assertRaisesRegex(
            InvalidDatabaseError,
            r"Error opening database file \(README.rst\). "
            r"Is this a valid MaxMind DB file\?",
        ):
            open_database("README.rst", self.mode)

    # This is from https://github.com/maxmind/MaxMind-DB-Reader-python/issues/58
    def test_database_with_invalid_utf8_key(self) -> None:
        reader = open_database(
            "tests/data/bad-data/maxminddb-python/bad-unicode-in-map-key.mmdb",
            self.mode,
        )
        with self.assertRaises(UnicodeDecodeError):
            reader.get_with_prefix_len("163.254.149.39")

    def test_too_many_constructor_args(self) -> None:
        with self.assertRaises(TypeError):
            self.reader_class("README.md", self.mode, 1)  # type: ignore[arg-type,call-arg]

    def test_bad_constructor_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, r"Unsupported open mode \(100\)"):
            self.reader_class("README.md", mode=100)  # type:  ignore[arg-type]

    def test_no_constructor_args(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            r" 1 required positional argument|"
            r"\(pos 1\) not found|"
            r"takes at least 2 arguments|"
            r"function missing required argument \'database\' \(pos 1\)",
        ):
            self.reader_class()  # type:  ignore[call-arg]

    def test_too_many_get_args(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        with self.assertRaises(TypeError):
            reader.get(self.ipf("1.1.1.1"), "blah")  # type:  ignore[call-arg]
        reader.close()

    def test_no_get_args(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        with self.assertRaises(TypeError):
            reader.get()  # type:  ignore[call-arg]
        reader.close()

    def test_incorrect_get_arg_type(self) -> None:
        reader = open_database("tests/data/test-data/GeoIP2-City-Test.mmdb", self.mode)
        with self.assertRaisesRegex(
            TypeError,
            "argument 1 must be a string or ipaddress object",
        ):
            reader.get(1)  # type:  ignore[arg-type]
        reader.close()

    def test_metadata_args(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        with self.assertRaises(TypeError):
            reader.metadata("blah")  # type:  ignore[call-arg]
        reader.close()

    def test_metadata_unknown_attribute(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        metadata = reader.metadata()
        with self.assertRaisesRegex(
            AttributeError,
            r"'(maxminddb\.extension\.)?Metadata' object has no attribute 'blah'",
        ):
            metadata.blah  # type:  ignore[attr-defined]  # noqa: B018
        reader.close()

    def test_close(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        reader.close()

    def test_double_close(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        reader.close()
        # Check that calling close again doesn't raise an exception
        reader.close()

    def test_closed_get(self) -> None:
        if self.mode in [MODE_MEMORY, MODE_FD]:
            return
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        reader.close()
        with self.assertRaisesRegex(
            ValueError,
            "Attempt to read from a closed MaxMind DB.|closed",
        ):
            reader.get(self.ipf("1.1.1.1"))

    def test_with_statement(self) -> None:
        filename = "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb"
        with open_database(filename, self.mode) as reader:
            self._check_ip_v4(reader, filename)
        self.assertEqual(reader.closed, True)

    def test_with_statement_close(self) -> None:
        filename = "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb"
        reader = open_database(filename, self.mode)
        reader.close()

        with (
            self.assertRaisesRegex(
                ValueError,
                "Attempt to reopen a closed MaxMind DB",
            ),
            reader,
        ):
            pass

    def test_closed(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        self.assertEqual(reader.closed, False)
        reader.close()
        self.assertEqual(reader.closed, True)

    def _reinitialize(self, reader: Any, path: str, mode: int) -> None:  # noqa: ANN401
        if mode == MODE_FD:
            with open(path, "rb") as database:
                reader.__init__(database, mode)
        else:
            reader.__init__(path, mode)

    def test_iterate_uninitialized_reader(self) -> None:
        reader = self.reader_class.__new__(self.reader_class)
        # The C reader raises in iter(), the pure Python reader in next().
        with self.assertRaisesRegex(ValueError, "closed MaxMind DB"):
            next(iter(reader))

    def test_close_uninitialized_reader(self) -> None:
        reader = self.reader_class.__new__(self.reader_class)
        self.assertTrue(reader.closed)
        reader.close()
        self.assertTrue(reader.closed)

    def test_reinitialize_reopens_the_reader(self) -> None:
        reader = open_database(
            f"{_TEST_DATA_DIR}/MaxMind-DB-test-ipv4-24.mmdb",
            self.mode,
        )
        self.addCleanup(reader.close)
        iterator = iter(reader)
        next(iterator)
        self._reinitialize(reader, _DECODER_DB, self.mode)
        self.assertEqual(reader.metadata().database_type, "MaxMind DB Decoder Test")
        # The iterator walked the old database, so it must stop.
        with self.assertRaisesRegex(ValueError, "reopened MaxMind DB"):
            next(iterator)

        reader.close()
        self._reinitialize(reader, _DECODER_DB, self.mode)
        self.assertFalse(reader.closed)
        self.assertIsNotNone(reader.get("::1.1.1.0"))

    def test_reinitialize_at_the_last_record(self) -> None:
        # The last record of this database is the right child of the root, so
        # no node of the walk remains after it.
        reader = open_database(
            f"{_TEST_DATA_DIR}/MaxMind-DB-test-decoder-value-limit.mmdb",
            self.mode,
        )
        self.addCleanup(reader.close)
        count = sum(1 for _ in reader)
        iterator = iter(reader)
        for _ in range(count):
            next(iterator)
        self._reinitialize(reader, _DECODER_DB, self.mode)
        with self.assertRaisesRegex(ValueError, "reopened MaxMind DB"):
            next(iterator)

    def test_iterate_after_close(self) -> None:
        reader = open_database(_DECODER_DB, self.mode)
        iterator = iter(reader)
        next(iterator)
        reader.close()
        with self.assertRaisesRegex(ValueError, "closed MaxMind DB"):
            next(iterator)

    def test_failed_reinitialize(self) -> None:
        reader = open_database(_DECODER_DB, self.mode)
        self.addCleanup(reader.close)

        # A failed reinit leaves the old database open.
        with self.assertRaisesRegex(ValueError, "Unsupported open mode"):
            self._reinitialize(reader, _DECODER_DB, 100)
        if self.mode != MODE_FD:
            with self.assertRaises(FileNotFoundError):
                self._reinitialize(reader, "missing.mmdb", self.mode)
        with self.assertRaises(InvalidDatabaseError):
            self._reinitialize(reader, "README.rst", self.mode)
        self.assertFalse(reader.closed)
        self.assertEqual(reader.metadata().database_type, "MaxMind DB Decoder Test")
        self.assertIsNotNone(reader.get("::1.1.1.0"))

    def test_closed_metadata(self) -> None:
        reader = open_database(
            "tests/data/test-data/MaxMind-DB-test-decoder.mmdb",
            self.mode,
        )
        reader.close()

        # The primary purpose of this is to ensure the extension doesn't
        # segfault
        try:
            metadata = reader.metadata()
        except OSError as ex:
            self.assertEqual(
                "Attempt to read from a closed MaxMind DB.",
                str(ex),
                "extension throws exception",
            )
        else:
            self.assertIsNotNone(metadata, "pure Python implementation returns value")

    def test_reading_from_buffer(self) -> None:
        filename = "tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb"
        with open(filename, "rb") as f:
            buf = io.BytesIO(f.read())
        # we have to use unpatched open_database here because the patched version
        # calls open() on our buffer
        reader = maxminddb.open_database(buf, MODE_FD)
        self._check_ip_v4(reader, filename)
        reader.close()

    if os.name != "nt":

        def test_multiprocessing(self):
            self._check_concurrency(self.mp.Process)

        def test_threading(self):
            self._check_concurrency(threading.Thread)

        def _check_concurrency(self, worker_class) -> None:  # noqa: ANN001
            reader = open_database(
                "tests/data/test-data/GeoIP2-Domain-Test.mmdb",
                self.mode,
            )

            def lookup(pipe) -> None:  # noqa: ANN001
                try:
                    for i in range(32):
                        reader.get(self.ipf(f"65.115.240.{i}"))
                    pipe.send(1)
                except:  # noqa: E722
                    pipe.send(0)
                finally:
                    if worker_class is self.mp.Process:  # type: ignore[attr-defined]
                        reader.close()
                    pipe.close()

            pipes = [self.mp.Pipe() for _ in range(32)]
            procs = [worker_class(target=lookup, args=(c,)) for (_, c) in pipes]
            for proc in procs:
                proc.start()
            for proc in procs:
                proc.join()

            reader.close()

            count = sum([p.recv() for (p, _) in pipes])

            self.assertEqual(count, 32, "expected number of successful lookups")

    def _check_metadata(
        self,
        reader: Reader,
        ip_version: int,
        record_size: int,
    ) -> None:
        metadata = reader.metadata()

        self.assertEqual(2, metadata.binary_format_major_version, "major version")
        self.assertEqual(metadata.binary_format_minor_version, 0)
        self.assertGreater(metadata.build_epoch, 1373571901)
        self.assertEqual(metadata.database_type, "Test")

        self.assertEqual(
            {"en": "Test Database", "zh": "Test Database Chinese"},
            metadata.description,
        )
        self.assertEqual(metadata.ip_version, ip_version)
        self.assertEqual(metadata.languages, ["en", "zh"])
        self.assertGreater(metadata.node_count, 36)

        self.assertEqual(metadata.record_size, record_size)

    def _check_ip_v4(self, reader: Reader, file_name: str) -> None:
        for i in range(6):
            address = "1.1.1." + str(pow(2, i))
            self.assertEqual(
                {"ip": address},
                reader.get(self.ipf(address)),
                "found expected data record for " + address + " in " + file_name,
            )

        pairs = {
            "1.1.1.3": "1.1.1.2",
            "1.1.1.5": "1.1.1.4",
            "1.1.1.7": "1.1.1.4",
            "1.1.1.9": "1.1.1.8",
            "1.1.1.15": "1.1.1.8",
            "1.1.1.17": "1.1.1.16",
            "1.1.1.31": "1.1.1.16",
        }
        for key_address, value_address in pairs.items():
            data = {"ip": value_address}

            self.assertEqual(
                data,
                reader.get(self.ipf(key_address)),
                "found expected data record for " + key_address + " in " + file_name,
            )

        for ip in ["1.1.1.33", "255.254.253.123"]:
            self.assertIsNone(reader.get(self.ipf(ip)))

    def _check_ip_v6(self, reader: Reader, file_name: str) -> None:
        subnets = ["::1:ffff:ffff", "::2:0:0", "::2:0:40", "::2:0:50", "::2:0:58"]

        for address in subnets:
            self.assertEqual(
                {"ip": address},
                reader.get(self.ipf(address)),
                "found expected data record for " + address + " in " + file_name,
            )

        pairs = {
            "::2:0:1": "::2:0:0",
            "::2:0:33": "::2:0:0",
            "::2:0:39": "::2:0:0",
            "::2:0:41": "::2:0:40",
            "::2:0:49": "::2:0:40",
            "::2:0:52": "::2:0:50",
            "::2:0:57": "::2:0:50",
            "::2:0:59": "::2:0:58",
        }

        for key_address, value_address in pairs.items():
            self.assertEqual(
                {"ip": value_address},
                reader.get(self.ipf(key_address)),
                "found expected data record for " + key_address + " in " + file_name,
            )

        for ip in ["1.1.1.33", "255.254.253.123", "89fa::"]:
            self.assertIsNone(reader.get(self.ipf(ip)))


def has_maxminddb_extension() -> bool:
    return maxminddb.extension is not None and hasattr(
        maxminddb.extension,
        "Reader",
    )


@unittest.skipIf(
    not has_maxminddb_extension() and not os.environ.get("MM_FORCE_EXT_TESTS"),
    "No C extension module found. Skipping tests",
)
class TestExtensionReader(BaseTestReader):
    mode = MODE_MMAP_EXT

    if has_maxminddb_extension():
        reader_class = maxminddb.extension.Reader

    def test_map_key_that_is_not_a_string_is_rejected(self) -> None:
        data = bytearray(
            pathlib.Path(f"{_TEST_DATA_DIR}/MaxMind-DB-test-ipv4-24.mmdb").read_bytes(),
        )
        # Change the type of the "ip" key from a string to a uint16.
        data[data.index(b"\x42ip")] = 0xA2
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "int-key.mmdb"
            path.write_bytes(data)
            with (
                maxminddb.extension.Reader(path) as reader,
                self.assertRaisesRegex(InvalidDatabaseError, "not a string"),
            ):
                reader.get("1.1.1.1")

    def test_invalid_utf8_key_does_not_leak(self) -> None:
        def fail_to_decode(count: int) -> None:
            for _ in range(count):
                with contextlib.suppress(UnicodeDecodeError):
                    reader.get("163.254.149.39")

        with maxminddb.extension.Reader(
            "tests/data/bad-data/maxminddb-python/bad-unicode-in-map-key.mmdb",
        ) as reader:
            fail_to_decode(100)
            gc.collect()
            tracemalloc.start()
            try:
                before, _ = tracemalloc.get_traced_memory()
                fail_to_decode(2000)
                gc.collect()
                after, _ = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
        # A leaked dict on each failure keeps about 128 KB.
        self.assertLess(after - before, 16_000)


@unittest.skipIf(
    not has_maxminddb_extension() and not os.environ.get("MM_FORCE_EXT_TESTS"),
    "No C extension module found. Skipping tests",
)
class TestExtensionReaderWithIPObjects(BaseTestReader):
    mode = MODE_MMAP_EXT
    use_ip_objects = True

    if has_maxminddb_extension():
        reader_class = maxminddb.extension.Reader


@unittest.skipIf(
    not has_maxminddb_extension() and not os.environ.get("MM_FORCE_EXT_TESTS"),
    "No C extension module found. Skipping tests",
)
class TestExtensionObjects(unittest.TestCase):
    """Objects in states that crashed the extension."""

    def test_new_metadata_requires_arguments(self) -> None:
        metadata_class = maxminddb.extension.Metadata
        with self.assertRaisesRegex(TypeError, "missing required argument"):
            metadata_class.__new__(metadata_class)

    def test_metadata_missing_argument(self) -> None:
        with self.assertRaisesRegex(TypeError, "missing required argument"):
            maxminddb.extension.Metadata(binary_format_major_version=2)  # type: ignore[call-arg]

    def test_metadata_too_many_arguments(self) -> None:
        with self.assertRaisesRegex(TypeError, "at most 9"):
            maxminddb.extension.Metadata(**_METADATA_FIELDS, unknown=1)  # type: ignore[call-arg]

    def test_iterate_uninitialized_reader(self) -> None:
        reader_class = maxminddb.extension.Reader
        reader = reader_class.__new__(reader_class)
        with self.assertRaisesRegex(ValueError, "closed MaxMind DB"):
            iter(reader)

    def test_enter_uninitialized_reader(self) -> None:
        reader_class = maxminddb.extension.Reader
        reader = reader_class.__new__(reader_class)
        with self.assertRaisesRegex(ValueError, "closed MaxMind DB"):
            reader.__enter__()

    def test_path_finalizer_can_close_the_reader(self) -> None:
        # A bytes subclass from __fspath__ can run code when init releases
        # it. If init still held the write lock, a close() on another thread
        # would wait for it forever on free-threaded Python. Run in a
        # subprocess with a timeout.
        program = textwrap.dedent(
            """
            import sys
            import threading

            from maxminddb.extension import Reader

            reader = Reader.__new__(Reader)

            class FinalizingBytes(bytes):
                def __del__(self):
                    worker = threading.Thread(target=reader.close)
                    worker.start()
                    worker.join()

            class Path:
                def __fspath__(self):
                    return FinalizingBytes(sys.argv[1].encode())

            reader.__init__(Path())
            if not reader.closed:
                sys.exit("the finalizer did not close the reader")
            print("ok")
            """,
        )
        self._run_program(program)

    def test_finalizer_during_a_read_cannot_reopen_the_reader(self) -> None:
        # With the GIL, a GC can run a finalizer during a decode, on Python
        # 3.10 and 3.11. If the finalizer reopened the reader there, the
        # decode would read the unmapped database and crash.
        program = textwrap.dedent(
            """
            import gc
            import sys

            from maxminddb.extension import Reader

            reader = Reader(sys.argv[1])

            class Reopen:
                def __init__(self):
                    self.cycle = self

                def __del__(self):
                    try:
                        reader.__init__(sys.argv[1])
                    except RuntimeError:
                        pass

            gc.set_threshold(1)
            for _ in range(2000):
                Reopen()
                if reader.get("::1.1.1.0") is None:
                    sys.exit("get() lost the record")
                Reopen()
                try:
                    next(iter(reader))
                except ValueError:
                    # A finalizer between iter() and next() reopened it.
                    pass
            print("ok")
            """,
        )
        self._run_program(program)

    def _run_program(self, program: str) -> None:
        # Put this process's maxminddb first, and keep the harness's paths.
        paths = [str(pathlib.Path(maxminddb.__file__).parent.parent)]
        if os.environ.get("PYTHONPATH"):
            paths.append(os.environ["PYTHONPATH"])
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}
        path = pathlib.Path(_DECODER_DB).resolve()
        with tempfile.TemporaryDirectory() as directory:
            # Run from an empty directory so the child imports the same
            # maxminddb as this process, not a source tree in the cwd.
            result = subprocess.run(  # noqa: S603
                [sys.executable, "-c", program, str(path)],
                capture_output=True,
                text=True,
                check=False,
                cwd=directory,
                env=env,
                timeout=60,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_initialize_after_close_on_uninitialized_reader(self) -> None:
        reader_class = maxminddb.extension.Reader
        reader = reader_class.__new__(reader_class)
        reader.close()
        self.assertTrue(reader.closed)
        reader.__init__(_DECODER_DB)  # type: ignore[misc]
        with reader:
            self.assertIsNotNone(reader.get("::1.1.1.0"))

    def test_reinitialize_metadata_changes_nothing(self) -> None:
        metadata = maxminddb.extension.Metadata(**_METADATA_FIELDS)
        metadata.__init__(**{**_METADATA_FIELDS, "record_size": 28})  # type: ignore[misc]
        self.assertEqual(metadata.record_size, 24)

    @unittest.skipUnless(
        hasattr(sys, "getrefcount") and not sysconfig.get_config_var("Py_GIL_DISABLED"),
        "needs CPython reference counts on a build with the GIL",
    )
    def test_freed_objects_release_their_type(self) -> None:
        with maxminddb.extension.Reader(_DECODER_DB) as reader:
            classes = [type(reader), type(reader.metadata()), type(iter(reader))]
        before = [sys.getrefcount(c) for c in classes]
        for _ in range(10):
            with maxminddb.extension.Reader(_DECODER_DB) as reader:
                reader.metadata()
                iter(reader)
        self.assertEqual([sys.getrefcount(c) for c in classes], before)

    def test_iterator_type_is_not_instantiable(self) -> None:
        with maxminddb.extension.Reader(_DECODER_DB) as reader:
            iterator_class = type(iter(reader))
        # The message differs across Python versions, so check only the type.
        with self.assertRaises(TypeError):
            iterator_class()
        with self.assertRaises(TypeError):
            iterator_class.__new__(iterator_class)


class TestAutoReader(BaseTestReader):
    mode = MODE_AUTO

    reader_class: type[maxminddb.extension.Reader | maxminddb.reader.Reader]
    if has_maxminddb_extension():
        reader_class = maxminddb.extension.Reader
    else:
        reader_class = maxminddb.reader.Reader


class TestMMAPReader(BaseTestReader):
    mode = MODE_MMAP
    reader_class = maxminddb.reader.Reader


# We want one pure Python test to use IP objects, it doesn't
# really matter which one.
class TestMMAPReaderWithIPObjects(BaseTestReader):
    mode = MODE_MMAP
    use_ip_objects = True
    reader_class = maxminddb.reader.Reader


class TestFileReader(BaseTestReader):
    mode = MODE_FILE
    reader_class = maxminddb.reader.Reader


class TestMemoryReader(BaseTestReader):
    mode = MODE_MEMORY
    reader_class = maxminddb.reader.Reader


class TestFDReader(BaseTestReader):
    def setUp(self) -> None:
        self.open_database_patcher = mock.patch(__name__ + ".open_database")
        self.addCleanup(self.open_database_patcher.stop)
        self.open_database = self.open_database_patcher.start()
        self.open_database.side_effect = get_reader_from_file_descriptor

    mode = MODE_FD
    reader_class = maxminddb.reader.Reader


class TestReaderInitialization(unittest.TestCase):
    def test_reinitialize_from_a_source_that_returns_the_same_mmap(self) -> None:
        with open(_DECODER_DB, "rb") as database:
            buffer = mmap.mmap(database.fileno(), 0, access=mmap.ACCESS_READ)
        self.addCleanup(buffer.close)

        class Source:
            def read(self) -> mmap.mmap:
                return buffer

        reader = maxminddb.reader.Reader(Source(), MODE_FD)  # type: ignore[arg-type]
        # A reinit must not close the buffer that it then uses.
        reader.__init__(Source(), MODE_FD)  # type: ignore[misc]
        self.assertIsNotNone(reader.get("::1.1.1.0"))

    def test_reinitialize_from_the_same_source(self) -> None:
        ipv4 = pathlib.Path(f"{_TEST_DATA_DIR}/MaxMind-DB-test-ipv4-24.mmdb")
        ipv6 = pathlib.Path(f"{_TEST_DATA_DIR}/MaxMind-DB-test-ipv6-24.mmdb")

        class OneBuffer:
            """Return the same bytearray from each read()."""

            def __init__(self) -> None:
                self.buffer = bytearray(ipv4.read_bytes())

            def read(self) -> bytearray:
                return self.buffer

        # BytesIO.read() returns the same bytes object after seek(0).
        bytes_io = io.BytesIO(ipv4.read_bytes())
        one_buffer = OneBuffer()

        def reopen_bytes_io() -> None:
            bytes_io.seek(0)

        def reopen_one_buffer() -> None:
            one_buffer.buffer[:] = ipv6.read_bytes()

        for source, change in (
            (bytes_io, reopen_bytes_io),
            (one_buffer, reopen_one_buffer),
        ):
            with self.subTest(source=type(source).__name__):
                reader = maxminddb.reader.Reader(source, MODE_FD)  # type: ignore[arg-type]
                self.addCleanup(reader.close)
                iterator = iter(reader)
                next(iterator)
                change()
                reader.__init__(source, MODE_FD)  # type: ignore[misc]
                with self.assertRaisesRegex(ValueError, "reopened MaxMind DB"):
                    next(iterator)

    def test_empty_search_tree_is_accepted(self) -> None:
        data = pathlib.Path(
            f"{_TEST_DATA_DIR}/MaxMind-DB-test-ipv4-24.mmdb"
        ).read_bytes()
        original = b"node_count\xc1\xa3"
        self.assertEqual(data.count(original), 1)
        with (
            io.BytesIO(data.replace(original, b"node_count\xc0")) as database,
            maxminddb.reader.Reader(database, MODE_FD) as reader,
        ):
            self.assertIsNone(reader.get("1.1.1.1"))
            self.assertEqual(list(reader), [])

    def test_invalid_tree_metadata_is_rejected_on_open(self) -> None:
        data = pathlib.Path(
            f"{_TEST_DATA_DIR}/MaxMind-DB-test-ipv4-24.mmdb"
        ).read_bytes()
        cases = (
            (b"record_size\xa1\x18", b"record_size\xa1\x1e", "Unknown record size: 30"),
            (
                b"node_count\xc1\xa3",
                b"node_count\x04\x01\xff\xff\xff\xff",
                "Invalid node count: -1",
            ),
        )
        for original, replacement, message in cases:
            with self.subTest(message=message):
                self.assertEqual(data.count(original), 1)
                with (
                    io.BytesIO(data.replace(original, replacement)) as database,
                    self.assertRaisesRegex(InvalidDatabaseError, message),
                    maxminddb.reader.Reader(database, MODE_FD),
                ):
                    pass

    def test_failed_initialization_closes_buffer(self) -> None:
        reader_class = maxminddb.reader.Reader
        marker = b"\xab\xcd\xefMaxMind.com"
        cases = (
            (b"not a database", InvalidDatabaseError, "Is this a valid MaxMind DB"),
            (marker + b"\x40", InvalidDatabaseError, "Error reading metadata"),
            (marker + b"\xe0", TypeError, "required keyword-only arguments"),
            (
                pathlib.Path(
                    f"{_TEST_DATA_DIR}/MaxMind-DB-test-metadata-payload-limit.mmdb"
                ).read_bytes(),
                InvalidDatabaseError,
                _PAYLOAD_TOO_LARGE,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "invalid.mmdb"
            for mode in (MODE_FILE, MODE_MMAP):
                for data, error, message in cases:
                    with self.subTest(mode=mode, message=message):
                        path.write_bytes(data)
                        with (
                            _bounded(),
                            mock.patch.object(
                                maxminddb.reader,
                                "_close_buffer",
                                wraps=maxminddb.reader._close_buffer,  # noqa: SLF001
                            ) as close_buffer,
                            self.assertRaisesRegex(error, message),
                        ):
                            reader_class(path, mode)
                        close_buffer.assert_called_once()
                        buffer = close_buffer.call_args.args[0]
                        if mode == MODE_FILE:
                            self.assertTrue(buffer._handle.closed)  # noqa: SLF001
                        else:
                            self.assertTrue(buffer.closed)


class TestSearchTreeNodes(unittest.TestCase):
    def test_28_bit_records_preserve_high_nibbles(self) -> None:
        # Node decoding needs only the record size and buffer, not a database.
        reader = object.__new__(maxminddb.reader.Reader)
        reader._record_size = 28  # noqa: SLF001
        # The middle byte holds the left record's high nibble, then the right's.
        reader._buffer = bytes.fromhex("aabbcc de ff0011 123456 f8 789abc")  # noqa: SLF001
        self.assertEqual(reader._read_node(0, 0), 0xDAABBCC)  # noqa: SLF001
        self.assertEqual(reader._read_node(0, 1), 0xEFF0011)  # noqa: SLF001
        self.assertEqual(reader._read_node(1, 0), 0xF123456)  # noqa: SLF001
        self.assertEqual(reader._read_node(1, 1), 0x8789ABC)  # noqa: SLF001


class TestOldReader(unittest.TestCase):
    def test_old_reader(self) -> None:
        reader = maxminddb.Reader("tests/data/test-data/MaxMind-DB-test-decoder.mmdb")
        record = cast("dict", reader.get("::1.1.1.0"))

        self.assertEqual(record["array"], [1, 2, 3])
        reader.close()


del BaseTestReader
