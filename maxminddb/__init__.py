# pylint:disable=C0111
import os

try:
    if os.environ.get('MAXMINDDB_PURE_PYTHON'):
        raise ImportError()
    from maxminddb.extension import Reader, InvalidDatabaseError
except ImportError:
    from maxminddb.decoder import InvalidDatabaseError
    from maxminddb.reader import Reader


__title__ = 'maxminddb'
__version__ = '0.3.1'
__author__ = 'Gregory Oschwald'
__license__ = 'Apache License, Version 2.0'
__copyright__ = 'Copyright 2014 Maxmind, Inc.'
