#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import logging
import mock
import os
import sys
import threading

from multiprocessing import Process, Pipe

import maxminddb

from maxminddb.compat import compat_ip_address

try:
    import maxminddb.extension
except ImportError:
    maxminddb.extension = None

from maxminddb import open_database, InvalidDatabaseError
from maxminddb.compat import FileNotFoundError
from maxminddb.const import (MODE_AUTO, MODE_MMAP_EXT, MODE_MMAP, MODE_FILE,
                             MODE_MEMORY, MODE_FD)

if sys.version_info[:2] == (2, 6):
    import unittest2 as unittest
else:
    import unittest

if sys.version_info[0] == 2:
    unittest.TestCase.assertRaisesRegex = unittest.TestCase.assertRaisesRegexp
    unittest.TestCase.assertRegex = unittest.TestCase.assertRegexpMatches


def get_reader_from_file_descriptor(filepath, mode):
    """Patches open_database() for class TestFDReader()."""
    if mode == MODE_FD:
        with open(filepath, 'rb') as mmdb_fh:
            return maxminddb.open_database(mmdb_fh, mode)
    else:
        # There are a few cases where mode is statically defined in
        # BaseTestReader(). In those cases just call an unpatched
        # open_database() with a string path.
        return maxminddb.open_database(filepath, mode)


class BaseTestReader(object):
    def test_reader(self):
        for record_size in [24, 28, 32]:
            for ip_version in [4, 6]:
                file_name = (
                    'tests/data/test-data/MaxMind-DB-test-ipv' +
                    str(ip_version) + '-' + str(record_size) + '.mmdb')
                reader = open_database(file_name, self.mode)

                self._check_metadata(reader, ip_version, record_size)

                if ip_version == 4:
                    self._check_ip_v4(reader, file_name)
                else:
                    self._check_ip_v6(reader, file_name)
                reader.close()

    def test_decoder(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        record = reader.get('::1.1.1.0')

        self.assertEqual(record['array'], [1, 2, 3])
        self.assertEqual(record['boolean'], True)
        self.assertEqual(record['bytes'], bytearray(b'\x00\x00\x00*'))
        self.assertEqual(record['double'], 42.123456)
        self.assertAlmostEqual(record['float'], 1.1)
        self.assertEqual(record['int32'], -268435456)
        self.assertEqual({
            'mapX': {
                'arrayX': [7, 8, 9],
                'utf8_stringX': 'hello'
            },
        }, record['map'])

        self.assertEqual(record['uint16'], 100)
        self.assertEqual(record['uint32'], 268435456)
        self.assertEqual(record['uint64'], 1152921504606846976)
        self.assertEqual(record['utf8_string'], 'unicode! ☯ - ♫')

        self.assertEqual(1329227995784915872903807060280344576,
                         record['uint128'])
        reader.close()

    def test_no_ipv4_search_tree(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-no-ipv4-search-tree.mmdb',
            self.mode)

        self.assertEqual(reader.get('1.1.1.1'), '::0/64')
        self.assertEqual(reader.get('192.1.1.1'), '::0/64')
        reader.close()

    def test_ipv6_address_in_ipv4_database(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb', self.mode)
        with self.assertRaisesRegex(ValueError, 'Error looking up 2001::. '
                                    'You attempted to look up an IPv6 address '
                                    'in an IPv4-only database'):
            reader.get('2001::')
        reader.close()

    def test_no_extension_exception(self):
        real_extension = maxminddb.extension
        maxminddb.extension = None
        with self.assertRaisesRegex(
                ValueError,
                'MODE_MMAP_EXT requires the maxminddb.extension module to be available'
        ):
            open_database('tests/data/test-data/MaxMind-DB-test-decoder.mmdb',
                          MODE_MMAP_EXT)
        maxminddb.extension = real_extension

    def test_ip_object_lookup(self):
        reader = open_database('tests/data/test-data/GeoIP2-City-Test.mmdb',
                               self.mode)
        with self.assertRaisesRegex(
                TypeError, "must be str(?:ing)?, not IPv6Address"):
            reader.get(compat_ip_address('2001:220::'))
        reader.close()

    def test_broken_database(self):
        reader = open_database('tests/data/test-data/'
                               'GeoIP2-City-Test-Broken-Double-Format.mmdb',
                               self.mode)
        with self.assertRaisesRegex(InvalidDatabaseError,
                                    "The MaxMind DB file's data "
                                    "section contains bad data \(unknown data "
                                    "type or corrupt data\)"):
            reader.get('2001:220::')
        reader.close()

    def test_ip_validation(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        self.assertRaisesRegex(ValueError,
                               "'not_ip' does not appear to be an IPv4 or "
                               "IPv6 address", reader.get, ('not_ip'))
        reader.close()

    def test_missing_database(self):
        self.assertRaisesRegex(FileNotFoundError, "No such file or directory",
                               open_database, 'file-does-not-exist.mmdb',
                               self.mode)

    def test_nondatabase(self):
        self.assertRaisesRegex(InvalidDatabaseError,
                               'Error opening database file \(README.rst\). '
                               'Is this a valid MaxMind DB file\?',
                               open_database, 'README.rst', self.mode)

    def test_too_many_constructor_args(self):
        cls = self.readerClass[0]
        self.assertRaises(TypeError, cls, 'README.md', self.mode, 1)

    def test_bad_constructor_mode(self):
        cls = self.readerClass[0]
        self.assertRaisesRegex(
            ValueError,
            'Unsupported open mode \(100\)',
            cls,
            'README.md',
            mode=100)

    def test_no_constructor_args(self):
        cls = self.readerClass[0]
        self.assertRaisesRegex(
            TypeError,
            ' 1 required positional argument|\(pos 1\) not found|takes at least 2 arguments',
            cls)

    def test_too_many_get_args(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        self.assertRaises(TypeError, reader.get, ('1.1.1.1', 'blah'))
        reader.close()

    def test_no_get_args(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        self.assertRaises(TypeError, reader.get)
        reader.close()

    def test_metadata_args(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        self.assertRaises(TypeError, reader.metadata, ('blah'))
        reader.close()

    def test_metadata_unknown_attribute(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        metadata = reader.metadata()
        with self.assertRaisesRegex(AttributeError, "'Metadata' object has no "
                                    "attribute 'blah'"):
            metadata.blah
        reader.close()

    def test_close(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        reader.close()

    def test_double_close(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        reader.close()
        self.assertIsNone(reader.close(),
                          'Double close does not throw an exception')

    def test_closed_get(self):
        if self.mode in [MODE_MEMORY, MODE_FD]:
            return
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        reader.close()
        self.assertRaisesRegex(ValueError,
                               'Attempt to read from a closed MaxMind DB.'
                               '|closed', reader.get, ('1.1.1.1'))

    def test_with_statement(self):
        filename = 'tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb'
        with open_database(filename, self.mode) as reader:
            self._check_ip_v4(reader, filename)
        self.assertEqual(reader.closed, True)

    def test_with_statement_close(self):
        filename = 'tests/data/test-data/MaxMind-DB-test-ipv4-24.mmdb'
        reader = open_database(filename, self.mode)
        reader.close()

        def use_with(reader):
            with reader:
                pass

        self.assertRaisesRegex(ValueError,
                               'Attempt to reopen a closed MaxMind DB',
                               use_with, reader)

    def test_closed(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        self.assertEqual(reader.closed, False)
        reader.close()
        self.assertEqual(reader.closed, True)

    # XXX - Figure out whether we want to have the same behavior on both the
    #       extension and the pure Python reader. If we do, the pure Python
    #       reader will need to throw an exception or the extension will need
    #       to keep the metadata in memory.
    def test_closed_metadata(self):
        reader = open_database(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
        reader.close()

        # The primary purpose of this is to ensure the extension doesn't
        # segfault
        try:
            metadata = reader.metadata()
        except IOError as ex:
            self.assertEqual('Attempt to read from a closed MaxMind DB.',
                             str(ex), 'extension throws exception')
        else:
            self.assertIsNotNone(metadata,
                                 'pure Python implementation returns value')

    def test_multiprocessing(self):
        self._check_concurrency(Process)

    def test_threading(self):
        self._check_concurrency(threading.Thread)

    if sys.version_info[0] == 2:

        def test_byte_ip_on_python2(self):
            reader = open_database(
                'tests/data/test-data/MaxMind-DB-test-decoder.mmdb', self.mode)
            record = reader.get(b'::1.1.1.0')

    def _check_concurrency(self, worker_class):
        reader = open_database('tests/data/test-data/GeoIP2-Domain-Test.mmdb',
                               self.mode)

        def lookup(pipe):
            try:
                for i in range(32):
                    reader.get('65.115.240.{i}'.format(i=i))
                pipe.send(1)
            except:
                pipe.send(0)
            finally:
                if worker_class is Process:
                    reader.close()
                pipe.close()

        pipes = [Pipe() for _ in range(32)]
        procs = [worker_class(target=lookup, args=(c, )) for (p, c) in pipes]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join()

        reader.close()

        count = sum([p.recv() for (p, c) in pipes])

        self.assertEqual(count, 32, 'expected number of successful lookups')

    def _check_metadata(self, reader, ip_version, record_size):
        metadata = reader.metadata()

        self.assertEqual(2, metadata.binary_format_major_version,
                         'major version')
        self.assertEqual(metadata.binary_format_minor_version, 0)
        self.assertGreater(metadata.build_epoch, 1373571901)
        self.assertEqual(metadata.database_type, 'Test')

        self.assertEqual({
            'en': 'Test Database',
            'zh': 'Test Database Chinese'
        }, metadata.description)
        self.assertEqual(metadata.ip_version, ip_version)
        self.assertEqual(metadata.languages, ['en', 'zh'])
        self.assertGreater(metadata.node_count, 36)

        self.assertEqual(metadata.record_size, record_size)

    def _check_ip_v4(self, reader, file_name):
        for i in range(6):
            address = '1.1.1.' + str(pow(2, i))
            self.assertEqual({
                'ip': address
            },
                             reader.get(address),
                             'found expected data record for ' + address +
                             ' in ' + file_name)

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

            self.assertEqual(data,
                             reader.get(key_address),
                             'found expected data record for ' + key_address +
                             ' in ' + file_name)

        for ip in ['1.1.1.33', '255.254.253.123']:
            self.assertIsNone(reader.get(ip))

    def _check_ip_v6(self, reader, file_name):
        subnets = [
            '::1:ffff:ffff', '::2:0:0', '::2:0:40', '::2:0:50', '::2:0:58'
        ]

        for address in subnets:
            self.assertEqual({
                'ip': address
            },
                             reader.get(address),
                             'found expected data record for ' + address +
                             ' in ' + file_name)

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
            self.assertEqual({
                'ip': value_address
            },
                             reader.get(key_address),
                             'found expected data record for ' + key_address +
                             ' in ' + file_name)

        for ip in ['1.1.1.33', '255.254.253.123', '89fa::']:
            self.assertIsNone(reader.get(ip))


def has_maxminddb_extension():
    return maxminddb.extension and hasattr(maxminddb.extension, 'Reader')


@unittest.skipIf(not has_maxminddb_extension()
                 and not os.environ.get('MM_FORCE_EXT_TESTS'),
                 'No C extension module found. Skipping tests')
class TestExtensionReader(BaseTestReader, unittest.TestCase):
    mode = MODE_MMAP_EXT

    if has_maxminddb_extension():
        readerClass = [maxminddb.extension.Reader]


class TestAutoReader(BaseTestReader, unittest.TestCase):
    mode = MODE_AUTO

    if has_maxminddb_extension():
        readerClass = [maxminddb.extension.Reader]
    else:
        readerClass = [maxminddb.reader.Reader]


class TestMMAPReader(BaseTestReader, unittest.TestCase):
    mode = MODE_MMAP
    readerClass = [maxminddb.reader.Reader]


class TestFileReader(BaseTestReader, unittest.TestCase):
    mode = MODE_FILE
    readerClass = [maxminddb.reader.Reader]


class TestMemoryReader(BaseTestReader, unittest.TestCase):
    mode = MODE_MEMORY
    readerClass = [maxminddb.reader.Reader]


class TestFDReader(BaseTestReader, unittest.TestCase):
    def setUp(self):
        self.open_database_patcher = mock.patch('reader_test.open_database')
        self.addCleanup(self.open_database_patcher.stop)
        self.open_database = self.open_database_patcher.start()
        self.open_database.side_effect = get_reader_from_file_descriptor

    mode = MODE_FD
    readerClass = [maxminddb.reader.Reader]


class TestOldReader(unittest.TestCase):
    def test_old_reader(self):
        reader = maxminddb.Reader(
            'tests/data/test-data/MaxMind-DB-test-decoder.mmdb')
        record = reader.get('::1.1.1.0')

        self.assertEqual(record['array'], [1, 2, 3])
        reader.close()
