"""pysftp specific exceptions"""

from __future__ import annotations


class ConnectionException(Exception):
    """Exception raised for connection problems

    Attributes:
        host     -- the host that could not be reached
        port     -- the port that was tried
        message  -- explanation of the error
    """

    def __init__(self, host: str, port: int) -> None:
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self, host, port)
        self.host = host
        self.port = port
        self.message = f"Could not connect to host:port.  {host}:{port}"

    def __str__(self) -> str:
        return self.message


class CredentialException(Exception):
    """Exception raised for credential problems

    Attributes:
        message  -- explanation of the error
    """

    def __init__(self, message: str) -> None:
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self, message)
        self.message = message


class HostKeysException(Exception):
    """raised when a problem with HostKeys is encountered"""
