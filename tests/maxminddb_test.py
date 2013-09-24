#!/usr/bin/env python
# -*- coding: utf-8 -*-

from maxminddb import Reader, InvalidDatabaseError
import sys
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
                file_name = ('maxmind-db/test-data/MaxMind-DB-test-ipv' +
                             str(ip_version) + '-' + str(record_size) + '.mmdb')
                reader = Reader(file_name)

                self._check_metadata(reader, ip_version, record_size)

                if ip_version == 4:
                    self._check_ip_v4(reader, file_name)
                else:
                    self._check_ip_v6(reader, file_name)

    def test_decoder(self):
        reader = Reader('maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb')
        record = reader.get('::1.1.1.0')

        self.assertEqual([1, 2, 3], record['array'])
        self.assertEqual(True, record['boolean'])
        self.assertEqual(bytearray(b'\x00\x00\x00*'), record['bytes'])
        self.assertEqual(42.123456, record['double'])
        self.assertAlmostEqual(1.1, record['float'])
        self.assertEqual(-268435456, record['int32'])
        self.assertEqual(
            {
                'mapX': {
                    'arrayX': [7, 8, 9],
                    'utf8_stringX': 'hello'
                },
            },
            record['map']
        )

        self.assertEqual(100, record['uint16'])
        self.assertEqual(268435456, record['uint32'])
        self.assertEqual(1152921504606846976, record['uint64'])
        self.assertEqual('unicode! ☯ - ♫', record['utf8_string'])

        self.assertEqual(
            1329227995784915872903807060280344576,
            record['uint128']
        )

    def test_ip_validation(self):
        reader = Reader('maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb')
        self.assertRaisesRegexp(ValueError,
                                'The value "not_ip" is not a valid IP address.',
                                reader.get, ('not_ip'))

    def test_missing_database(self):
        self.assertRaisesRegexp(ValueError,
                                'The file "file-does-not-exist.mmdb" does not exist or is not readable.',
                                Reader, ('file-does-not-exist.mmdb'))

    def test_nondatabase(self):
        self.assertRaisesRegexp(InvalidDatabaseError,
                                'Error opening database file \(README.md\). Is this a valid MaxMind DB file\?',
                                Reader, ('README.md'))

    def test_too_many_constructor_args(self):
        self.assertRaises(TypeError, Reader, ('README.md', 1))

    def test_no_constructor_args(self):
        self.assertRaises(TypeError, Reader, ())

    def test_too_many_get_args(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        self.assertRaises(TypeError, reader.get, ('1.1.1.1', 'blah'))

    def test_no_get_args(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        self.assertRaises(TypeError, reader.get, ())

    def test_metadata_args(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        self.assertRaises(TypeError, reader.metadata, ('blah'))

    def test_close(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()

    def test_double_close(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()
        self.assertRaisesRegexp(IOError,
                                'Attempt to close a closed MaxMind DB.',
                                reader.close)

    def test_closed_get(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()
        self.assertRaisesRegexp(IOError,
                                'Attempt to read from a closed MaxMind DB.',
                                reader.get, ('1.1.1.1'))

    def test_closed_metadata(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()
        self.assertRaisesRegexp(IOError,
                                'Attempt to read from a closed MaxMind DB.',
                                reader.metadata)

    def _check_metadata(self, reader, ip_version, record_size):
        metadata = reader.metadata()

        self.assertEqual(
            2,
            metadata.binary_format_major_version,
            'major version'
        )
        self.assertEqual(0, metadata.binary_format_minor_version)
        self.assertEqual(1373571901, metadata.build_epoch)
        self.assertEqual('Test', metadata.database_type)

        self.assertEqual(
            {'en': 'Test Database', 'zh': 'Test Database Chinese'},
            metadata.description
        )

        self.assertEqual(ip_version, metadata.ip_version)
        self.assertEqual(['en', 'zh'], metadata.languages)
        self.assertEqual(record_size / 4, metadata.node_byte_size)
        self.assertGreater(36, metadata.node_count)

        self.assertEqual(record_size, metadata.record_size)
        self.assertGreater(200, metadata.search_tree_size)

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
