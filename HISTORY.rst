.. :changelog:

History
-------

2.5.1 (2023-11-09)
++++++++++++++++++

* This is a re-release of 2.5.0 to address missing files from the sdist.
  Reported by Lumír 'Frenzy' Balhar. GitHub #132.

2.5.0 (2023-11-08)
++++++++++++++++++

* IMPORTANT: Python 3.8 or greater is required. If you are using an older
  version, please use an earlier release.
* Windows is now supported by the C extension.
* The ``Reader`` class now implements the ``__iter__`` method. This will
  return an iterator that iterates over all records in the database,
  excluding repeated aliased of the IPv4 network. Requested by
  Jean-Baptiste Braun and others. GitHub #23.
* The multiprocessing test now explicitly uses ``fork``. This allows it
  to run successfully on macOS. Pull request by Theodore Ni. GitHub #116.
* A vendored copy of ``libmaxminddb`` will now be used by default when
  building the extension. If you wish to continue using the system shared
  library, you may set the ``MAXMINDDB_USE_SYSTEM_LIBMAXMINDDB`` environment
  variable to a true value when building the extension. 
* The C extension now builds on Python 3.13.
* The C extension will now be built for PyPy.

2.4.0 (2023-06-28)
++++++++++++++++++

* Package metadata was migrated from ``setup.py`` to ``setup.cfg``. GitHub
  #113.
* The C extension now decrements the reference count on an object
  containing the database filename after its use in an error message rather
  than before. Pull request by Lumír 'Frenzy' Balhar. GitHub #114.

2.3.0 (2023-05-09)
++++++++++++++++++

* IMPORTANT: Python 3.7 or greater is required. If you are using an older
  version, please use an earlier release.
* ``distutils`` is no longer used for building the C extension.
* Missing ``Py_INCREF`` was added to module initialization for the C
  extension. Pull request by R. Christian McDonald. GitHub #106.

2.2.0 (2021-09-24)
++++++++++++++++++

* The return type for ``maxminddb.open_database()`` has been simplified
  to be just the ``Reader`` class as opposed to a union of that with
  the extension class. This is done by casting the extension to
  ``Reader``. The extension class has the same public API as the
  pure Python implementation. This simplifies type checking for users of
  this library. The ``Reader`` class is exposed as ``maxminddb.Reader``.
  Pull request by wouter bolsterlee. GitHub #88.
* ``maxminddb.__all__`` is now set to define a public API. Pull request
  by wouter bolsterlee. GitHub #88.
* Fix minor regression in ``repr`` output of ``maxminddb.reader.Metadata``
  in 2.1.0.

2.1.0 (2021-09-18)
++++++++++++++++++

* The C extension now correctly supports objects that implement the
  ``os.PathLike`` interface.
* When opening a database fails due to an access issue, the correct
  ``OSError`` subclass will now be thrown.
* The ``Metadata`` class object is now available from the C extension
  module as ``maxminddb.extension.Metadata`` rather than
  ``maxminddb.extension.extension``.
* Type stubs have been added for ``maxminddb.extension``.

2.0.3 (2020-10-16)
++++++++++++++++++

* The 2.0.0 release unintentionally required Python to be compiled with
  ``mmap`` support for the module to work. ``mmap`` is now optional
  again. Reported by john-heasman-cg. GitHub #76.

2.0.2 (2020-07-28)
++++++++++++++++++

* Added ``py.typed`` file per PEP 561. Reported by Árni Már Jónsson.

2.0.1 (2020-07-22)
++++++++++++++++++

* Fix minimum required python version in ``setup.py``. Pull request by
  Boros Gábor. GitHub #69 & #70.

2.0.0 (2020-07-21)
++++++++++++++++++

* IMPORTANT: Python 3.6 or greater is required. If you are using an older
  version, please use a 1.x.x release.
* Type hints have been added.

1.5.4 (2020-05-05)
++++++++++++++++++

* 1.5.3 was missing a test database. This release adds the test file.
  There are no other changes. Reported by Lumír 'Frenzy' Balhar. GitHub #60.

1.5.3 (2020-05-04)
++++++++++++++++++

* Fix a segfault when decoding a database with a corrupt data section.
  Reported by Robert Scott. GitHub #58.

1.5.2 (2019-12-20)
++++++++++++++++++

* Minor performance improvements in the pure Python reader.

1.5.1 (2019-09-27)
++++++++++++++++++

* Fix a possible segfault due to not correctly incrementing the reference
  on a returned object.

1.5.0 (2019-09-27)
++++++++++++++++++

* Python 3.3 and 3.4 are no longer supported.
* The extension source directory was moved to prevent an ``ImportWarning``
  when importing the module on Python 2 with ``-Wdefault`` set. Reported by
  David Szotten and Craig de Stigter. GitHub #31.
* The ``get`` method now accepts ``ipaddress.IPv4Address`` and
  ``ipaddress.IPv6Address`` objects in addition to strings.  This works with
  both the pure Python implementation as well as the extension. Based on a
  pull request #48 by Eric Pruitt. GitHub #50.
* A new method, ``get_with_prefix_len``, was added. This method returns a
  tuple containing the record and the prefix length.

1.4.1 (2018-06-22)
++++++++++++++++++

* Fix test failure on Python 3.7. Reported by Carl George. GitHub #35.

1.4.0 (2018-05-25)
++++++++++++++++++

* IMPORTANT: Previously, the pure Python reader would allow
  ``ipaddress.IPv4Address`` and ``ipaddress.IPv6Address`` objects when calling
  ``.get()``. This would fail with the C extension. The fact that these objects
  worked at all was an implementation detail and has varied with different
  releases. This release makes the pure Python implementation consistent
  with the extension. A ``TypeError`` will now be thrown if you attempt to
  use these types with either the pure Python implementation or the
  extension. The IP address passed to ``.get()`` should be a string type.
* Fix issue where incorrect size was used when unpacking some types with the
  pure Python reader. Reported by Lee Symes. GitHub #30.
* You may now pass in the database via a file descriptor rather than a file
  name when creating a new ``maxminddb.Reader`` object using ``MODE_FD``.
  This will read the database from the file descriptor into memory. Pull
  request by nkinkade. GitHub #33.

1.3.0 (2017-03-13)
++++++++++++++++++

* ``maxminddb.Reader`` and the C extension now support being used in a context
  manager. Pull request by Joakim Uddholm. GitHub #21 & #28.
* Provide a more useful error message when ``MODE_MMAP_EXT`` is requested but
  the C extension is not available.

1.2.3 (2017-01-11)
++++++++++++++++++

* Improve compatibility with other Python 2 ``ipaddress`` backports. Although
  ``ipaddress`` is highly recommended, ``py2-ipaddress`` and
  ``backport_ipaddress`` should now work. Incompatibility reported by
  John Zadroga on ``geoip2`` GitHub issue #41.

1.2.2 (2016-11-21)
++++++++++++++++++

* Fix to the classifiers in ``setup.py``. No code changes.

1.2.1 (2016-06-10)
++++++++++++++++++

* This module now uses the ``ipaddress`` module for Python 2 rather than the
  ``ipaddr`` module. Users should notice no behavior change beyond the change
  in dependencies.
* Removed ``requirements.txt`` from ``MANIFEST.in`` in order to stop warning
  during installation.
* Added missing test data.

1.2.0 (2015-04-07)
++++++++++++++++++

* Previously if ``MODE_FILE`` was used and the database was loaded before
  forking, the parent and children would use the same file table entry without
  locking causing errors reading the database due to the offset being changed
  by other processes. In ``MODE_FILE``, the reader will now use ``os.pread``
  when available and a lock when ``os.pread`` is not available (e.g., Python
  2). If you are using ``MODE_FILE`` on a Python without ``os.pread``, it is
  recommended that you open the database after forking to reduce resource
  contention.
* The ``Metadata`` class now overloads ``__repr__`` to provide a useful
  representation of the contents when debugging.
* An ``InvalidDatabaseError`` will now be thrown if the data type read from
  the database is invalid. Previously a ``KeyError`` was thrown.

1.1.1 (2014-12-10)
++++++++++++++++++

* On Python 3 there was a potential issue where ``open_database`` with
  ``MODE_AUTO`` would try to use the C extension when it was not available.
  This could cause the function to fail rather than falling back to a pure
  Python mode.

1.1.0 (2014-12-09)
++++++++++++++++++

* The pure Python reader now supports an optional file and memory mode in
  addition to the existing memory-map mode. If your Python does not provide
  the ``mmap`` module, the file mode will be used by default.
* The preferred method for opening a database is now the ``open_database``
  function in ``maxminddb``. This function now takes an optional read
  ``mode``.
* The C extension no longer creates its own ``InvalidDatabaseError`` class
  and instead uses the one defined in ``maxminddb.errors``.

1.0.0 (2014-09-22)
++++++++++++++++++

* First production release.
* Two potential C extension issues discovered by Coverity were fixed:
  - There was a small resource leak that occurred when the system ran out of
    memory.
  - There was a theoretical null pointer issue that would occur only if
    libmaxminddb returned invalid data.

0.3.3 (2014-04-09)
++++++++++++++++++

* Corrected initialization of objects in C extension and made the objects
  behave more similarly to their pure Python counterparts.

0.3.2 (2014-03-28)
++++++++++++++++++

* Switched to Apache 2.0 license.
* We now open the database file in read-only mode.
* Minor code clean-up.

0.3.1 (2014-02-11)
++++++++++++++++++

* Fixed packaging problem that caused ``import`` to fail.

0.3.0 (2014-02-11)
++++++++++++++++++

* This release includes a pure Python implementation of the database reader.
  If ``libmaxminddb`` is not available or there are compilation issues, the
  module will fall-back to the pure Python implementation.
* Minor changes were made to the exceptions of the C extension make them
  consistent with the pure Python implementation.

0.2.1 (2013-12-18)
++++++++++++++++++

* Removed -Werror compiler flag as it was causing problems for some OS X
  users.

0.2.0 (2013-10-15)
++++++++++++++++++

* Refactored code and fixed a memory leak when throwing an exception.

0.1.1 (2013-10-03)
++++++++++++++++++

* Added MANIFEST.in

0.1.0 (2013-10-02)
++++++++++++++++++

* Initial release
