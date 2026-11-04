# Troubleshooting

Each page below is titled with the exact error that pysftp 0.2.9 prints. It explains why the error
happens and shows the fix with pysftp-ng.

- [ImportError: cannot import name 'DSSKey' from 'paramiko'](importerror-dsskey.md)
- [AttributeError: 'Connection' object has no attribute '_sftp_live'](attributeerror-sftp-live.md)
- [SSHException: No hostkey for host ... found.](no-hostkey-for-host.md)
- [Incompatible ssh peer (no acceptable host key)](incompatible-ssh-peer.md)
- [SSHException: unpack requires a buffer of 4 bytes](unpack-requires-a-buffer.md)
- [SSHException: encountered EC key, expected DSA key](encountered-ec-key.md)

```{toctree}
:hidden:

importerror-dsskey
attributeerror-sftp-live
no-hostkey-for-host
incompatible-ssh-peer
unpack-requires-a-buffer
encountered-ec-key
```
