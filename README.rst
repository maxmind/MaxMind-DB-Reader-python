========================
MaxMind DB Python Module
========================

Beta Note
---------
This is a beta release. The API may change before the first production
release.

Description
-----------

This is a Python module for reading MaxMind DB files. The module includes both
a pure Python reader and an optional C extension.

MaxMind DB is a binary file format that stores data indexed by IP address
subnets (IPv4 or IPv6).

Installation
------------

If you want to use the C extension, you must first install `libmaxminddb
<https://github.com/maxmind/libmaxminddb>`_ C library installed before
installing this extension. If the library is not available, the module will
fall-back to a pure Python implementation.

To install maxminddb, type:

.. code-block:: bash

    $ pip install maxminddb

If you are not able to use pip, you may also use easy_install from the
source directory:

.. code-block:: bash

    $ easy_install .

Usage
-----

To use this module, you must first download or create a MaxMind DB file. We
provide `free GeoLite2 databases
<http://dev.maxmind.com/geoip/geoip2/geolite2>`_. These files must be
decompressed with ``gunzip``.

After you have obtained a database and importing the module, you must create a
``Reader`` object, providing the path to the file as the first argument to the
constructor. After doing this, you may call the ``get`` method with an IP
address on the object. This method will return the corresponding values for
the IP address from the database (e.g., a dictionary for GeoIP2/GeoLite2
databases). If the database does not contain a record for that IP address, the
method will return ``None``.

Example
-------

.. code-block:: pycon

    >>> import maxminddb
    >>>
    >>> reader = maxminddb.Reader('GeoLite2-City.mmdb')
    >>> reader.get('1.1.1.1')
    {'country': ... }
    >>>
    >>> # The optional 'close' method will release the resources to the
    >>> # system immediately.
    >>> reader.close()

Exceptions
----------

The module will return an ``InvalidDatabaseError`` if the database is corrupt
or otherwise invalid. A ``ValueError`` will be thrown if you look up an
invalid IP address or an IPv6 address in an IPv4 database.

Requirements
------------

This code requires Python 2.6+ or 3.3+. The C extension requires CPython. The
pure Python implementation has been tested with PyPy.

On Python 2, the `ipaddr module <https://code.google.com/p/ipaddr-py/>`_ is
required.

Versioning
----------

The MaxMind DB Python module uses `Semantic Versioning <http://semver.org/>`_.

Support
-------

Please report all issues with this code using the `GitHub issue tracker
<https://github.com/maxmind/MaxMind-DB-Reader-python/issues>`_

If you are having an issue with a MaxMind service that is not specific to this
API, please contact `MaxMind support <http://www.maxmind.com/en/support>`_ for
assistance.
