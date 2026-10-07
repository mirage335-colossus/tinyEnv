# Host graphics input provenance

[mesa-windows.json](mesa-windows.json) pins the exact Windows AMD64 binary archive
and two selected DLLs used only for local and CI graphics qualification. No binary
is stored here. The supplier build repository and release remain external sources;
the consumer takes an explicit retained archive and never silently reacquires it.

The input was inspected against release `26.2.3` and supplier build revision
`9d027e91d2ba2de7da37bf180f8d544945ae811c`. Full archive size and SHA256, selected
DLL sizes and hashes, PE architecture and imported DLL names were checked. The
supplier's exact build-information and build-script license files have independent
hashes in the lock. Those observations establish provenance and selected static
imports, not native Windows execution or complete redistribution permission.

The archive includes other APIs, processor variants and deployment scripts. The
helper selects only the two locked AMD64 WGL files and executes no supplier script.
Installed `7z` performs bounded listing and exact-member extraction to stdout;
archive paths never become extraction destinations.

## Source and notice closure

The binary archive provides a link to a user manual and **no license texts**.
Before redistributing a retained archive/group, collect and verify:

- The exact supplier build scripts, configuration, patches and build information
  at the locked commit, including their MIT license.
- Mesa `26.2.3` sources, component license files and applied build changes.
- LLVM `23.1.2` sources and applicable Apache license with LLVM exceptions.
- Source identities and applicable notices for linked components, including zlib
  and zstd as used by the supplier; distinguish build-only tools from code in the
  selected binaries using the supplier build configuration.
- The complete mapping from retained inputs to the distributed DLLs and a reviewed
  redistribution decision. A release version URL is a starting source reference,
  not a verified retained source archive hash.

The current lock deliberately records `redistribution.approved: false`. Local
acquisition and host qualification do not change that status. The helper has no
publication function and does not add drivers to SDK or application payloads.

See the [host qualification contract](../../docs/windows-graphics.md) for staging,
native evidence, cleanup and upgrades. The Linux fixture suite qualifies helper
mechanics; successful native WGL and GUI rendering evidence must come from the
actual Windows job before support is claimed.
