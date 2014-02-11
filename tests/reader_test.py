#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import sys

from maxminddb import Reader, InvalidDatabaseError
from maxminddb.compat import FileNotFoundError

if sys.version_info[:2] == (2, 6):
    import unittest2 as unittest
else:
    import unittest

if sys.version_info[0] == 2:
    unittest.TestCase.assertRaisesRegex = unittest.TestCase.assertRaisesRegexp
    unittest.TestCase.assertRegex = unittest.TestCase.assertRegexpMatches


class TestReader(unittest.TestCase):

    def test_reader(self):
        for record_size in [24, 28, 32]:
            for ip_version in [4, 6]:
                file_name = ('tests/data/test-data/MaxMind-DB-test-ipv' +
                             str(ip_version) + '-' + str(record_size) +
                             '.mmdb')
                reader = Reader(file_name)

                self._check_metadata(reader, ip_version, record_size)

                if ip_version == 4:
                    self._check_ip_v4(reader, file_name)
                else:
                    self._check_ip_v6(reader, file_name)

    def test_decoder(self):
        reader = Reader('tests/data/test-data/MaxMind-DB-test-decoder.mmdb')
        record = reader.get('::1.1.1.0')

        self.assertEqual(record['array'], [1, 2, 3])
        self.assertEqual(record['boolean'], True)
        self.assertEqual(record['bytes'], bytearray(b'\x00\x00\x00*'))
        self.assertEqual(record['double'], 42.123456)
        self.assertAlmostEqual(record['float'], 1.1)
        self.assertEqual(record['int32'], -268435456)
        self.assertEqual(
            {
                'mapX': {
                    'arrayX': [7, 8, 9],
                    'utf8_stringX': 'hello'
                },
            },
            record['map']
        )

        self.assertEqual(record['uint16'], 100)
        self.assertEqual(record['uint32'], 268435456)
        self.assertEqual(record['uint64'], 1152921504606846976)
        self.assertEqual(record['utf8_string'], 'unicode! ☯ - ♫')

        self.assertEqual(
            1329227995784915872903807060280344576,
            record['uint128']
        )

    def test_ipv6_address_in_ipv4_database(self):
        reader = Reader('tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb')
        with self.assertRaisesRegex(ValueError,
                                    'Error looking up 2001::. '
                                    'You attempted to look up an IPv6 address '
                                    'in an IPv4-only database'):
            reader.get('2001::')

    def test_broken_database(self):
        reader = Reader('tests/data/test-data/'
                        'GeoIP2-City-Test-Broken-Double-Format.mmdb')
        with self.assertRaisesRegex(InvalidDatabaseError,
                                    "The MaxMind DB file's data "
                                    "section contains bad data \(unknown data "
                                    "type or corrupt data\)"
                                    ):
            reader.get('2001:220::')

    def test_ip_validation(self):
        reader = Reader('tests/data/test-data/MaxMind-DB-test-decoder.mmdb')
        self.assertRaisesRegex(ValueError,
                               "'not_ip' does not appear to be an IPv4 or "
                               "IPv6 address",
                               reader.get, ('not_ip'))

    def test_missing_database(self):
        self.assertRaisesRegex(FileNotFoundError,
                               "No such file or directory: "
                               "u?'file-does-not-exist.mmdb'",
                               Reader, ('file-does-not-exist.mmdb'))

    def test_nondatabase(self):
        self.assertRaisesRegex(InvalidDatabaseError,
                               'Error opening database file \(README.rst\). '
                               'Is this a valid MaxMind DB file\?',
                               Reader, ('README.rst'))

    def test_too_many_constructor_args(self):
        self.assertRaises(TypeError, Reader, ('README.md', 1))

    def test_no_constructor_args(self):
        self.assertRaises(TypeError, Reader)

    def test_too_many_get_args(self):
        reader = Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        self.assertRaises(TypeError, reader.get, ('1.1.1.1', 'blah'))

    def test_no_get_args(self):
        reader = Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        self.assertRaises(TypeError, reader.get)

    def test_metadata_args(self):
        reader = Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        self.assertRaises(TypeError, reader.metadata, ('blah'))

    def test_metadata_unknown_attribute(self):
        reader = Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        metadata = reader.metadata()
        with self.assertRaisesRegex(AttributeError,
                                    "'Metadata' object has no "
                                    "attribute 'blah'"):
            metadata.blah

    def test_close(self):
        reader = Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()

    def test_double_close(self):
        reader = Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        self.assertIsNone(
            reader.close(), 'Double close does not throw an exception')

    def test_closed_get(self):
        reader = Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()
        self.assertRaisesRegex(ValueError,
                               'Attempt to read from a closed MaxMind DB.'
                               '|closed or invalid',
                               reader.get, ('1.1.1.1'))

    # XXX - Figure out whether we want to have the same behavior on both the
    #       extension and the pure Python reader. If we do, the pure Python
    #       reader will need to throw an exception or the extension will need
    #       to keep the metadata in memory.
    def test_closed_metadata(self):
        reader = Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()

        # The primary purpose of this is to ensure the extension doesn't
        # segfault
        try:
            metadata = reader.metadata()
        except IOError as ex:
            self.assertEqual('Attempt to read from a closed MaxMind DB.',
                             str(ex), 'extension throws exception')
        else:
            self.assertIsNotNone(
                metadata, 'pure Python implementation returns value')

    def _check_metadata(self, reader, ip_version, record_size):
        metadata = reader.metadata()

        self.assertEqual(
            2,
            metadata.binary_format_major_version,
            'major version'
        )
        self.assertEqual(metadata.binary_format_minor_version, 0)
        self.assertEqual(metadata.build_epoch, 1373571901)
        self.assertEqual(metadata.database_type, 'Test')

        self.assertEqual(
            {'en': 'Test Database', 'zh': 'Test Database Chinese'},
            metadata.description
        )
        self.assertEqual(metadata.ip_version, ip_version)
        self.assertEqual(metadata.languages, ['en', 'zh'])
        self.assertGreater(metadata.node_count, 36)

        self.assertEqual(metadata.record_size, record_size)

    def _check_ip_v4(self, reader, file_name):
        for i in range(6):
            address = '1.1.1.' + str(pow(2, i))
            self.assertEqual(
                {'ip': address},
                reader.get(address),
                'found expected data record for '
                + address + ' in ' + file_name
            )

        pairs = {
            '1.1.1.3': '1.1.1.2',
            '1.1.1.5': '1.1.1.4',
            '1.1.1.7': '1.1.1.4',
            '1.1.1.9': '1.1.1.8',
            '1.1.1.15': '1.1.1.8',
            '1.1.1.17': '1.1.1.16',
            '1.1.1.31': '1.1.1.16'
        }
        for key_address, value_address in pairs.items():
            data = {'ip': value_address}

            self.assertEqual(
                data,
                reader.get(key_address),
                'found expected data record for ' + key_address + ' in '
                + file_name
            )

        for ip in ['1.1.1.33', '255.254.253.123']:
            self.assertIsNone(reader.get(ip))

    def _check_ip_v6(self, reader, file_name):
        subnets = ['::1:ffff:ffff', '::2:0:0',
                   '::2:0:40', '::2:0:50', '::2:0:58']

        for address in subnets:
            self.assertEqual(
                {'ip': address},
                reader.get(address),
                'found expected data record for ' + address + ' in '
                + file_name
            )

        pairs = {
            '::2:0:1': '::2:0:0',
            '::2:0:33': '::2:0:0',
            '::2:0:39': '::2:0:0',
            '::2:0:41': '::2:0:40',
            '::2:0:49': '::2:0:40',
            '::2:0:52': '::2:0:50',
            '::2:0:57': '::2:0:50',
            '::2:0:59': '::2:0:58'
        }

        for key_address, value_address in pairs.items():
            self.assertEqual(
                {'ip':  value_address},
                reader.get(key_address),
                'found expected data record for ' + key_address + ' in '
                + file_name
            )

        for ip in ['1.1.1.33', '255.254.253.123', '89fa::']:
            self.assertIsNone(reader.get(ip))
