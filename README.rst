
.. code-block:: pycon

    >>> import maxminddb
    >>>
    >>> reader = maxminddb.Reader('GeoLite2-City.mmdb')
    >>> reader.get('1.1.1.1')
    {'country': ... }
