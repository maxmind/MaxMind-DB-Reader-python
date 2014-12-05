"""
maxminddb.reader
~~~~~~~~~~~~~~~~

This module contains the pure Python database reader and related classes.

"""
from __future__ import unicode_literals
import struct

from maxminddb.compat import byte_from_int, int_from_byte, ipaddress
from maxminddb.decoder import Decoder
from maxminddb.errors import InvalidDatabaseError


class Reader(object):

    """
    Instances of this class provide a reader for the MaxMind DB format. IP
    addresses can be looked up using the ``get`` method.
    """

    _DATA_SECTION_SEPARATOR_SIZE = 16
    _METADATA_START_MARKER = b"\xAB\xCD\xEFMaxMind.com"

    _ipv4_start = None

    def __init__(self, database, use_mmap=True):
        """Reader for the MaxMind DB file format

        Arguments:
        database -- A path to a valid MaxMind DB file such as a GeoIP2
                    database file.
        use_mmap -- If True, uses mmap to load the database. If False,
                    reads the entire database into memory
        """
        with open(database, 'rb') as db_file:
            if use_mmap:
                import mmap
                self._buffer = mmap.mmap(
                    db_file.fileno(), 0, access=mmap.ACCESS_READ)
                self._buffer_size = self._buffer.size()
            else:
                self._buffer = db_file.read()
                self._buffer_size = len(self._buffer)

        metadata_start = self._buffer.rfind(self._METADATA_START_MARKER,
                                            self._buffer_size - 128 * 1024)

        if metadata_start == -1:
            raise InvalidDatabaseError('Error opening database file ({0}). '
                                       'Is this a valid MaxMind DB file?'
                                       ''.format(database))

        metadata_start += len(self._METADATA_START_MARKER)
        metadata_decoder = Decoder(self._buffer, metadata_start)
        (metadata, _) = metadata_decoder.decode(metadata_start)
        self._metadata = Metadata(**metadata)  # pylint: disable=star-args

        self._decoder = Decoder(self._buffer, self._metadata.search_tree_size
                                + self._DATA_SECTION_SEPARATOR_SIZE)

    def metadata(self):
        """Return the metadata associated with the MaxMind DB file"""
        return self._metadata

    def get(self, ip_address):
        """Return the record for the ip_address in the MaxMind DB


        Arguments:
        ip_address -- an IP address in the standard string notation
        """
        address = ipaddress.ip_address(ip_address)

        if address.version == 6 and self._metadata.ip_version == 4:
            raise ValueError('Error looking up {0}. You attempted to look up '
                             'an IPv6 address in an IPv4-only database.'.format(
                                 ip_address))
        pointer = self._find_address_in_tree(address)

        return self._resolve_data_pointer(pointer) if pointer else None

    def _find_address_in_tree(self, ip_address):
        packed = ip_address.packed

        bit_count = len(packed) * 8
        node = self._start_node(bit_count)

        for i in range(bit_count):
            if node >= self._metadata.node_count:
                break
            bit = 1 & (int_from_byte(packed[i >> 3]) >> 7 - (i % 8))
            node = self._read_node(node, bit)
        if node == self._metadata.node_count:
            # Record is empty
            return 0
        elif node > self._metadata.node_count:
            return node

        raise InvalidDatabaseError('Invalid node in search tree')

    def _start_node(self, length):
        if self._metadata.ip_version != 6 or length == 128:
            return 0

        # We are looking up an IPv4 address in an IPv6 tree. Skip over the
        # first 96 nodes.
        if self._ipv4_start:
            return self._ipv4_start

        node = 0
        for _ in range(96):
            if node >= self._metadata.node_count:
                break
            node = self._read_node(node, 0)
        self._ipv4_start = node
        return node

    def _read_node(self, node_number, index):
        base_offset = node_number * self._metadata.node_byte_size

        record_size = self._metadata.record_size
        if record_size == 24:
            offset = base_offset + index * 3
            node_bytes = b'\x00' + self._buffer[offset:offset + 3]
        elif record_size == 28:
            (middle,) = struct.unpack(
                b'!B', self._buffer[base_offset + 3:base_offset + 4])
            if index:
                middle &= 0x0F
            else:
                middle = (0xF0 & middle) >> 4
            offset = base_offset + index * 4
            node_bytes = byte_from_int(
                middle) + self._buffer[offset:offset + 3]
        elif record_size == 32:
            offset = base_offset + index * 4
            node_bytes = self._buffer[offset:offset + 4]
        else:
            raise InvalidDatabaseError(
                'Unknown record size: {0}'.format(record_size))
        return struct.unpack(b'!I', node_bytes)[0]

    def _resolve_data_pointer(self, pointer):
        resolved = pointer - self._metadata.node_count + \
            self._metadata.search_tree_size

        if resolved > self._buffer_size:
            raise InvalidDatabaseError(
                "The MaxMind DB file's search tree is corrupt")

        (data, _) = self._decoder.decode(resolved)
        return data

    def close(self):
        """Closes the MaxMind DB file and returns the resources to the system"""
        self._buffer.close()


class Metadata(object):

    """Metadata for the MaxMind DB reader"""

    # pylint: disable=too-many-instance-attributes
    def __init__(self, **kwargs):
        """Creates new Metadata object. kwargs are key/value pairs from spec"""
        # Although I could just update __dict__, that is less obvious and it
        # doesn't work well with static analysis tools and some IDEs
        self.node_count = kwargs['node_count']
        self.record_size = kwargs['record_size']
        self.ip_version = kwargs['ip_version']
        self.database_type = kwargs['database_type']
        self.languages = kwargs['languages']
        self.binary_format_major_version = kwargs[
            'binary_format_major_version']
        self.binary_format_minor_version = kwargs[
            'binary_format_minor_version']
        self.build_epoch = kwargs['build_epoch']
        self.description = kwargs['description']

    @property
    def node_byte_size(self):
        """The size of a node in bytes"""
        return self.record_size // 4

    @property
    def search_tree_size(self):
        """The size of the search tree"""
        return self.node_count * self.node_byte_size
