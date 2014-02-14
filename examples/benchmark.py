#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import print_function

import argparse
import maxminddb
import random
import socket
import struct
import timeit

parser = argparse.ArgumentParser(description='Benchmark maxminddb.')
parser.add_argument('--count', default=250000, type=int,
                    help='number of lookups')
parser.add_argument('--file', default='GeoIP2-City.mmdb',
                    help='path to mmdb file')

args = parser.parse_args()

reader = maxminddb.Reader(args.file)


def lookup_ip_address():
    ip = socket.inet_ntoa(struct.pack('!L', random.getrandbits(32)))
    record = reader.get(str(ip))


elapsed = timeit.timeit('lookup_ip_address()',
                        setup='from __main__ import lookup_ip_address',
                        number=args.count)

print(args.count / elapsed, 'lookups per second')
