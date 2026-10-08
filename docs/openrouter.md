# Local OpenRouter access

[`tools/openrouter.py`](../tools/openrouter.py) is an optional developer client
using Python 3.9+ and its standard library. It has no effect on the application,
GUI, SDK, installed packages or normal offline builds. Only its explicit `check`
and `chat` commands contact OpenRouter. Chat sends the prompt you supply on
standard input; the helper does not collect repository files or conversation
history.

## Set up the key locally

From the repository root on Linux or macOS:

```sh
python3 tools/openrouter.py init
```

This creates `.env.openrouter` with empty settings and owner-only permissions
(`0600`). It refuses to overwrite an existing file. Open that local file in your
editor and enter the key after `OPENROUTER_API_KEY=`. Optionally set
`OPENROUTER_MODEL` to your chosen OpenRouter model slug. The tracked
[example](../.env.openrouter.example) contains no credentials and must stay empty.
Keep the real key out of chat messages, command arguments, shell history,
screenshots and saved logs.

The helper locates the configuration beside the repository root regardless of
the current working directory. It accepts literal `KEY=value` assignments,
optional matching single or double quotes, blank lines and full-line comments.
Only `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` are accepted. It does not execute
shell syntax, expand variables or source the file. An environment variable with
the same name overrides the corresponding file setting, including an empty value.
You may instead inject `OPENROUTER_API_KEY` through your local secret manager.

On POSIX systems, the helper refuses symlinks, nonregular files and configuration
files accessible to other users. After an editor changes permissions, restore
them with `chmod 600 .env.openrouter`. Windows users should supply environment
variables through a secure local mechanism; `init` cannot establish Windows ACLs
and refuses to create a file there.

## Check and use

```sh
# Local configuration only: no network and no credential values printed.
python3 tools/openrouter.py status

# Authenticate with OpenRouter without generating a completion.
python3 tools/openrouter.py check

# Replace provider/model with your selected model, or set OPENROUTER_MODEL.
printf '%s\n' 'Reply with a short greeting.' | \
  python3 tools/openrouter.py chat --model provider/model --max-tokens 256
```

Model selection is explicit, with `--model` overriding `OPENROUTER_MODEL`; there
is no automatically selected paid model. Chat may incur the selected model's
charges. Only submit content intended for that service. The default output limit
is 256 tokens, and online requests default to a 30-second socket timeout;
`--timeout` accepts 1–120 seconds and is not a total wall-clock deadline. Prompts
are limited to 65,536 characters and responses to 1 MiB. Requests are not
automatically retried.

The client uses OpenRouter's fixed HTTPS API endpoint with bearer authentication,
disables redirects, and suppresses server error bodies and exception details.
`check` reports authentication success without dumping key metadata. Chat prints
the response text with occurrences of the configured key redacted. It creates no
prompt, response or credential logs. Invalid configuration, missing required
settings and failed requests exit nonzero.

API references, checked 2026-10-07: [OpenRouter quickstart](https://openrouter.ai/docs/quickstart)
and [current API key endpoint](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key).

## Git and source archive protection

The repository ignores `.env` and `.env.*` at every directory level, including
`.env.openrouter` and backup names such as `.env.openrouter.bak`. Only
`.env.example` and `.env.*.example` are eligible for tracking. Verify your local
file without printing its contents:

```sh
git check-ignore -v .env.openrouter
git ls-files --error-unmatch .env.openrouter
```

The first command should report the ignore rule. The second should fail because
the file is untracked. Do not use `git add -f` for credentials: ignore rules do
not protect already tracked files or deliberately forced additions. The project's
source snapshot/archive helper also excludes these private environment files,
including in source trees without Git metadata. The repository-fork script copies
committed source, leaving local untracked configuration behind.
Common Emacs autosave/lock names (`#.env.openrouter#`, `.#.env.openrouter`)
and Vim swap names (`..env.openrouter.swp`) are excluded as well.

These controls cover ordinary Git use and the project's source archives. They
do not encrypt the file or exclude it from arbitrary directory backups or manual
uploads. Store editor backups under the ignored naming pattern. If a real key
ever enters Git history or an upload, revoke it at OpenRouter and replace it;
removing it from the latest file alone does not remove the disclosure.

## Focused verification

The registered offline test suite uses fake keys and mocked requests. It checks
configuration, private file creation, request construction, failure diagnostics,
redirect rejection and redaction. Source-identity tests check that environment
secrets cannot enter generated source archives. No test needs a real key or a
paid request.

```sh
./build.sh test dev --core-provider cpp --build-dir build/openrouter-checks \
  --test tools.openrouter --test tools.source_identity --test docs.links
```

The explicit C++ provider keeps this script-only check independent of Rust SDK
setup. It makes no statement about application or release qualification. Live
authentication remains a separate local step after you enter the key.
