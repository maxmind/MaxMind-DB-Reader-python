.. maxminddb documentation master file, created by
   sphinx-quickstart on Tue Apr  9 13:34:57 2013.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

.. toctree::
   :maxdepth: 3

.. include:: ../README.rst

======
Module
======

.. automodule:: maxminddb
    :members:
    :undoc-members:
    :show-inheritance:

======
Errors
======

.. automodule:: maxminddb.errors
    :members:
    :undoc-members:
    :show-inheritance:

===============
Database Reader
===============

.. automodule:: maxminddb.reader
    :members:
    :undoc-members:
    :show-inheritance:

=====
Types
=====

.. automodule:: maxminddb.types
    :members:
    :undoc-members:
    :exclude-members: Primitive, Record

.. The runtime values of these aliases contain AnyStr, so give the types that
   type checkers see.

.. autodata:: maxminddb.types.Primitive
    :annotation: = str | bytes | bytearray | bool | float | int

.. autodata:: maxminddb.types.Record
    :annotation: = Primitive | RecordList | RecordDict

==================
Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

:copyright: (c) 2013-2025 by MaxMind, Inc.
:license: Apache License, Version 2.0

