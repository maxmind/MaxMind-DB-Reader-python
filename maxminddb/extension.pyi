

# pylint: disable=E0601,E0602
from ipaddress import IPv4Address, IPv6Address
from os import PathLike
from typing import IO, Any, AnyStr

from typing_extensions import Self

from maxminddb.types import Record

class Reader:


    closed: bool = ...

    def __init__(
        self,
        database: AnyStr | int | PathLike | IO,
        mode: int = ...,
    ) -> None:
        ...

    def close(self) -> None:
        ...

    def get(self, ip_address: str | IPv6Address | IPv4Address) -> Record | None:
        ...

    def get_with_prefix_len(
        self,
        ip_address: str | IPv6Address | IPv4Address,
    ) -> tuple[Record | None, int]:
        ...

    def metadata(self) -> Metadata:
        ...

    def __enter__(self) -> Self: ...
    def __exit__(self, *args) -> None: ...

# pylint: disable=too-few-public-methods
class Metadata:


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
    """
    The Unix epoch for the build time of the database.
    """

    database_type: str
    """
    A string identifying the database type, e.g., "GeoIP2-City".
    """

    description: dict[str, str]
    """
    A map from locales to text descriptions of the database.
    """

    ip_version: int
    """
    The IP version of the data in a database. A value of "4" means the
    database only supports IPv4. A database with a value of "6" may support
    both IPv4 and IPv6 lookups.
    """

    languages: list[str]
    """
    A list of locale codes supported by the databse.
    """

    node_count: int
    """
    The number of nodes in the database.
    """

    record_size: int
    """
    The bit size of a record in the search tree.
    """

    def __init__(self, **kwargs: Any) -> None:
        ...
