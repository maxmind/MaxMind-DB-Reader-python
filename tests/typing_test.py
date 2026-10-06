# mypy: warn-unused-ignores
"""Static type checks for the public API.

mypy checks this file in the lint environment. The code does not run. Each
type: ignore marks a line that must fail the type check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import gzip
    import io
    from ipaddress import IPv4Network, IPv6Network
    from pathlib import Path

    from typing_extensions import assert_type

    import maxminddb
    import maxminddb.extension
    from maxminddb.types import Primitive, Record

    reader = maxminddb.open_database("GeoIP2-City.mmdb")
    assert_type(reader.get("1.1.1.1"), Record | None)
    assert_type(reader.get_with_prefix_len("1.1.1.1"), tuple[Record | None, int])
    for network, record in reader:
        assert_type(network, IPv4Network | IPv6Network)
        assert_type(record, Record)
    assert_type(reader.metadata().search_tree_size, int)
    with maxminddb.open_database(Path("GeoIP2-City.mmdb")) as path_reader:
        assert_type(path_reader, maxminddb.Reader)

    # Record includes the bytearray that the C extension returns for the
    # bytes type.
    value: Record = bytearray(b"\x00")

    # A TypeVar in either alias would give Record members of type Any.
    def check_not_generic(
        primitive: Primitive[str],  # type: ignore[type-arg]
        record: Record[str],  # type: ignore[type-arg]
    ) -> None:
        pass

    def check_mode_fd(gzip_file: gzip.GzipFile, text_file: io.TextIOWrapper) -> None:
        maxminddb.open_database(gzip_file, maxminddb.Mode.FD)
        maxminddb.open_database(text_file, maxminddb.Mode.FD)  # type: ignore[arg-type]

    extension_reader = maxminddb.extension.Reader("GeoIP2-City.mmdb")
    for network, record in extension_reader:
        assert_type(network, IPv4Network | IPv6Network)
        assert_type(record, Record)
    assert_type(extension_reader.metadata().node_byte_size, int)
    maxminddb.extension.Reader(3)  # type: ignore[arg-type]
