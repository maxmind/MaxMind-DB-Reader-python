#!/usr/bin/env python
# -*- coding: utf-8 -*-

from maxminddb import Reader
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
                             ip_version + '-' + recordSize + '.mmdb')
                reader = Reader(file_name)

                #$this->checkMetadata(reader, ip_version, recordSize)

                if ip_version == 4:
                    self.check_ip_v4(reader, file_name)
                else:
                    self.check_ip_v6(reader, file_name)

    def test_decoder(self):
        reader = Reader('maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb')
        record = reader.get('::1.1.1.0')

        self.assertEqual([1, 2, 3], record['array'])
        self.assertEqual(true, record['boolean'])
        self.assertEqual(pack('N', 42), record['bytes'])
        self.assertEqual(42.123456, record['double'])
        self.assertEqual(1.1000000238419, record['float'])
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
        self.assertEqual('1152921504606846976', record['uint64'])
        self.assertEqual('unicode! ☯ - ♫', record['utf8_string'])

        self.assertEqual(
            '1329227995784915872903807060280344576',
            record['uint128']
        )

    # /**
    #  * @expectedException InvalidArgumentException
    #  * @expectedExceptionMessage The value "not_ip" is not a valid IP address.
    #  */
    def test_ip_validation(self):
        reader = Reader('maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb')
        reader.get('not_ip')

    # /**
    #  * @expectedException InvalidArgumentException
    #  * @expectedExceptionMessage The file "file-does-not-exist.mmdb" does not exist or is not readable.
    #  */
    def test_missing_database(self):
        Reader('file-does-not-exist.mmdb')

    # /**
    #  * @expectedException MaxMind\Db\Reader\InvalidDatabaseException
    #  * @expectedExceptionMessage Error opening database file (README.md). Is this a valid MaxMind DB file?
    #  */
    def test_nondatabase(self):
        Reader('README.md')

    # /**
    #  * @expectedException InvalidArgumentException
    #  * @expectedExceptionMessage The constructor takes exactly one argument.
    #  */
    def test_too_many_constructor_args(self):
        Reader('README.md', 1)

    # /**
    #  * @expectedException InvalidArgumentException
    #  *
    #  * This test only matters for the extension.
    #  */
    def test_no_constructor_args(self):
        Reader()

    # /**
    #  * @expectedException InvalidArgumentException
    #  * @expectedExceptionMessage Method takes exactly one argument.
    #  */
    def test_too_many_get_args(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.get('1.1.1.1', 'blah')

    # /**
    #  * @expectedException InvalidArgumentException
    #  *
    #  * This test only matters for the extension.
    #  */
    def test_no_get_args(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )

    # /**
    #  * @expectedException InvalidArgumentException
    #  * @expectedExceptionMessage Method takes no arguments.
    #  */
    def test_metadata_args(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.metadata('blah')

    def test_close(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()

    # /**
    #  * @expectedException BadMethodCallException
    #  * @expectedExceptionMessage Attempt to close a closed MaxMind DB.
    #  */
    def test_double_close(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()
        reader.close()

    # /**
    #  * @expectedException BadMethodCallException
    #  * @expectedExceptionMessage Attempt to read from a closed MaxMind DB.
    #  */
    def test_closed_get(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()
        reader.get('1.1.1.1')

    # /**
    #  * @expectedException BadMethodCallException
    #  * @expectedExceptionMessage Attempt to read from a closed MaxMind DB.
    #  */
    def test_closed_metadata(self):
        reader = Reader(
            'maxmind-db/test-data/MaxMind-DB-test-decoder.mmdb'
        )
        reader.close()
        reader.metadata()

    def _check_metadata(self, reader, ip_version, record_size):
        metadata = reader.metadata()

        self.assertEqual(
            2,
            metadata.binaryFormatMajorVersion,
            'major version'
        )
        self.assertEqual(0, metadata.binaryFormatMinorVersion)
        self.assertEqual(1373571901, metadata.buildEpoch)
        self.assertEqual('Test', metadata.databaseType)

        self.assertEqual(
            {'en': 'Test Database', 'zh': 'Test Database Chinese'},
            metadata.description
        )

        self.assertEqual(ip_version, metadata.ip_version)
        self.assertEqual(['en', 'zh'], metadata.languages)
        self.assertEqual(recordSize / 4, metadata.nodeByteSize)
        self.assertGreater(36, metadata.nodeCount)

        self.assertEqual(recordSize, metadata.recordSize)
        self.assertGreater(200, metadata.searchTreeSize)

    def _check_ip_v4(self, reader, file_name):
        for i in range(6):
            address = '1.1.1.' + pow(2, i)
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
        for key_address, value_address in pairs.iteritems():
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

        for key_address, value_address in pairs.iteritems():
            self.assertEqual(
                {'ip':  value_address},
                reader.get(key_address),
                'found expected data record for ' + key_address + ' in '
                + file_name
            )

        for ip in ['1.1.1.33', '255.254.253.123', '89fa::']:
            self.assertIsNone(reader.get(ip))
