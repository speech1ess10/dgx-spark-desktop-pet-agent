# Security

The macOS client never executes model-generated shell commands. Supported local
tools are restricted to:

- opening `Desktop`, `Documents`, or `Downloads`;
- searching for a file inside those folders and opening a user-selected match;
- opening a small allowlist of macOS applications.

Every local tool invocation requires a confirmation dialog. File deletion,
moving, overwriting, arbitrary paths, and arbitrary commands are intentionally
not implemented.

Keep the Spark API bound to `127.0.0.1` and reach it through an SSH tunnel. Do
not expose port 7000 directly to the public internet; this MVP has no user
authentication or TLS termination.

Please report security issues privately to the repository owner rather than
opening a public issue with exploit details.

