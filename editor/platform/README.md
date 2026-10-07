# Editor-private native services

`ProjectFiles` pins an explicitly opened project directory, accepts relative
regular-file paths, and rejects parent traversal, symlink/reparse components and
special files. POSIX operations use directory descriptors and `openat`; Windows
pins each parent without delete sharing and rejects reparse points. Files are
valid UTF-8 bytes, preserving BOM and line endings. The default per-file editing
limit is 8 MiB. No project opening operation runs code.

Capture with `read` or `inspect` before saving. `inspect` can capture a nonexistent
leaf but its parents must exist; create them explicitly with `ensure_directory`.
For process working directories, `directory(".")` resolves the project root and
`directory(relative)` validates an existing ordinary nested directory. File-only
`absolute(relative)` remains the source navigation/external-editor path service.
A save compares identity and exact original bytes, writes and flushes a temporary
file beside its destination, rechecks, then publishes. Missing leaves cannot be
clobbered if another editor creates them during publication. Existing-file
publication uses a final cooperative comparison, rather than an operating-system
compare-and-swap guarantee against unrelated simultaneous writers. Keep project
writers quiescent during a generated batch. File-save failure leaves a CodeBuffer's
unsaved bytes and original snapshot available. An error after publication can
mean bytes were saved but directory durability was unconfirmed; reload before
retrying. File ownership/ACLs beyond ordinary permissions are not preserved.

`save_batch` stages old and new bytes for every file, writes a bounded journal
with SHA-256 digests, and publishes the revision marker last. Its 64 MiB total
journal budget and 4096-file limit are independent of each source-file limit.
`recovery_pending` blocks generation/build until explicit `recover_batch` finishes
the new revision. Recovery validates every staging file and target before writing;
it refuses foreign changes. Preserve the journal/backups when that happens.
Manually resolve a foreign target to its recorded new bytes, then recover again.
Successful completion removes the journal before removing backup files, so an
interruption during cleanup cannot leave a journal referring to deleted backups.
Interrupted staging before journal publication can leave unused
`.foundation-editor-batch-*` files; those may be manually removed when no editor
save is running. Batch publication does not provide atomic visibility to other
programs and never enrolls handwritten files unless the caller explicitly selects
them.

`ProcessRunner` accepts an argv array and an explicit existing working directory.
It never evaluates shell syntax. `poll` continuously drains output while retaining
at most the configured log budget (2 MiB by default); excess bytes are discarded
and reported. A Linux private, single-threaded child subreaper joins every adopted
descendant, including children that create new sessions. A Windows suspended child
is assigned to a non-breakaway, kill-on-close Job Object before its code runs.
A parent command leaving live descendants fails after terminating/joining them.
Cancel/close terminates and joins owned work. Commands must not transfer writable
handles to unrelated services; this is cooperative process ownership, not hostile
process confinement. Other native platforms fail explicitly for process execution
until an equivalent owner exists.

External editors use this same argv API; the caller chooses/configures the
executable and appends the validated file path as an argument. These services do
not interpret `$EDITOR` or shell command strings. Build/Run remain explicit user
UI actions. A nonzero build result must never launch a stale executable.

Focused Linux tests cover file conflicts, UTF-8/CRLF/BOM, symlink paths, permissions,
checked new files, journal recovery, SHA-256 vectors, process errors, literal argv,
bounded noisy logs, cancellation and escaped-session descendant cleanup. Windows
implementations are present; Windows execution remains separately unverified.
