API reference
=============

Everything below is importable from the ``pysftp`` module, with the same names,
arguments and defaults as pysftp 0.2.9.

.. module:: pysftp

Connection
----------

.. autoclass:: Connection
   :members:

CnOpts
------

.. autoclass:: CnOpts
   :members:

Helpers
-------

.. autofunction:: st_mode_to_int

.. autoclass:: WTCallbacks
   :members:

.. autofunction:: path_advance

.. autofunction:: path_retreat

.. autofunction:: reparent

.. autofunction:: walktree

.. autofunction:: cd

.. autofunction:: known_hosts

Exceptions
----------

.. autoexception:: ConnectionException

.. autoexception:: CredentialException

.. autoexception:: HostKeysException
