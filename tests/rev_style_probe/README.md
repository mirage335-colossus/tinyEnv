# Focused Rev module probe

`tools/rev_probe.py` configures this isolated fixture against a verified retained
GUI input group. It compiles four actual pinned Rev modules and checks style
comparison and invalidation behavior, without window, graphics or GUI dependency
builds. It is a compiler diagnostic, not application or release qualification.

`style.cpp` is adapted from Data Pump `tests/test_rev_style.cpp` at revision
`2bbd92c63e22490e7708c6bc3d878eb4d1fe09e7`. That project-owned fixture is
Copyright (c) 2026 mirage335, dedicated under CC0-1.0; the complete original license
is retained in `COPYING`. The CMake fixture follows the original four-module
regression layout. Rev source is supplied by the existing pinned GUI source
input group and retains its separate notices and distribution terms.

The test keeps assertions active in Release by using explicit checked exceptions.
The two CTest cases must both run and pass. Clang's ambiguous reversed comparison
extension is an error, matching the stricter MSVC behavior. Do not replace the
production modules with simplified stand-ins or count a configure-only run as a
pass. The surrounding Python fixtures test failure/evidence handling; a real
compiler run is explicitly selected and needs installed CMake 3.28+, Ninja and
a supported module compiler with its matching scanner.
