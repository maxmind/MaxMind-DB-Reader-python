"""C extension database reader and related classes."""

from collections.abc import Iterator
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network

from typing_extensions import Self

from maxminddb.reader import Metadata as Metadata
from maxminddb.types import Record, StrOrBytesPath

class Reader:
    """A C extension implementation of a reader for the MaxMind DB format.

    IP addresses can be looked up using the ``get`` method.
    """

    closed: bool = ...

    def __init__(
        self,
        database: StrOrBytesPath,
        mode: int = ...,
    ) -> None:
        """Reader for the MaxMind DB file format.

        Arguments:
            database: A path to a valid MaxMind DB file such as a GeoIP database
                      file.
            mode: mode to open the database with. The only supported modes are
                  MODE_AUTO and MODE_MMAP_EXT.

        """

    def close(self) -> None:
        """Close the MaxMind DB file and returns the resources to the system."""

    def get(self, ip_address: str | IPv6Address | IPv4Address) -> Record | None:
        """Return the record for the ip_address in the MaxMind DB.

        Arguments:
            ip_address: an IP address in the standard string notation

        """

    def get_with_prefix_len(
        self,
        ip_address: str | IPv6Address | IPv4Address,
    ) -> tuple[Record | None, int]:
        """Return a tuple with the record and the associated prefix length.

        Arguments:
            ip_address: an IP address in the standard string notation

        """

    def metadata(self) -> Metadata:
        """Return the metadata associated with the MaxMind DB file."""

    def __iter__(self) -> Iterator[tuple[IPv4Network | IPv6Network, Record]]: ...
    def __enter__(self) -> Self: ...
    def __exit__(self, *args: object) -> None: ...
