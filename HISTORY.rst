.. :changelog:

History
-------

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
