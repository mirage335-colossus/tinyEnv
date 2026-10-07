# Installed manuals

The [CLI manual](foundation-cli.1) documents the actual command contract. The
[package manual](software-foundation.7) explains installed paths, runtime needs,
GUI choices, developer consumption and removal. They use portable `man` macros
and require no documentation generator or network access during a normal build.

Preview with `man -l docs/man/foundation-cli.1` or validate formatting with
`groff -man -Tutf8 docs/man/foundation-cli.1`. Install both source manuals through
CMake on every platform; Unix readers discover them through `MANPATH`, while
other consumers can read the source or use a separately supplied reader.

Keep options, exit status and input bounds synchronized with the CLI contract.
An installed-consumer check verifies that both files survive relocation. Native
package wrappers expose variant-specific manual names alongside their launchers;
the manuals' underlying application contract remains shared.
