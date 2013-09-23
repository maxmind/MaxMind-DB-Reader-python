#!/usr/bin/python3

import MMDB
mmdb = MMDB.new(
    "/usr/local/share/GeoIP/GeoIP2-City.mmdb")

print(mmdb.get("24.24.24.24"))
