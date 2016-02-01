.. :changelog:

History
-------

1.2.1 (2016-XX-XX)
++++++++++++++++++

* The dependency on the ``ipaddr`` module for Python 2 has been removed.

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
