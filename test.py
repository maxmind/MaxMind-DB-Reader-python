#!/usr/bin/python3

import maxminddb
mmdb = maxminddb.Reader(
    "/usr/local/share/GeoIP/GeoIP2-City.mmdb")

print(mmdb.get("24.24.24.24"))
