#!/bin/sh
# Keep shell syntax compatible with traditional SVR4 Bourne sh and with Dash.
# Git and the external utilities still need the versions documented in README.
# Backticks and expr are intentional: traditional Bourne sh needs them.
# shellcheck disable=SC2006,SC2003
set -eu

# Project settings: edit these defaults, or set the variables in the environment.
# PROJECT_NAME is also the destination when no directory argument is supplied.
# PROJECT_AUTHOR is a copyright/CC0 name or screenname, independent of Git identity.
# Leave it empty to preserve the foundation's existing attribution.
PROJECT_NAME=${PROJECT_NAME:-}
PROJECT_AUTHOR=${PROJECT_AUTHOR:-}
# Ordered defaults: one URL or local path per line, without shell quoting each
# entry. Spaces are preserved. Command-line source arguments replace this list.
DEFAULT_SOURCE_URLS=${DEFAULT_SOURCE_URLS-'https://github.com/mirage335-colossus/software-foundation.git'}
# Capture the date on the machine running this script.
PROJECT_DATE=`date +%Y-%m-%d`

usage() {
    cat <<'EOF'
Usage: fork.sh [--] [DESTINATION [SOURCE_URL ...]]
       fork.sh --help

Create an independent repository containing only main and its latest original
commit (depth one), with no tags or remote. No commit or Git identity is needed.
DESTINATION defaults to PROJECT_NAME in the current directory. It must not exist,
and its parent directory must already exist.
Try SOURCE_URLs in order, using main from the first successful clone.
Without SOURCE_URLs, use the DEFAULT_SOURCE_URLS list configured at the top.
Git handles HTTPS, SSH, file:// URLs and local paths (relative to your cwd).

Set PROJECT_NAME, PROJECT_AUTHOR and DEFAULT_SOURCE_URLS in the environment or
edit the configuration at the top of this script. An explicit destination can
also supply the project name through its basename. PROJECT_AUTHOR is optional
copyright/CC0 attribution, including a screenname; it never sets Git identity.
The current date is captured automatically. Recognized foundation attribution in
LICENSE and README is updated when PROJECT_AUTHOR is set, leaving unstaged edits
for you to review and commit. Suggested next commands are printed on completion.

Example:
  PROJECT_NAME='my-project' PROJECT_AUTHOR='my-screenname' ./fork.sh
  ./fork.sh ../my-project /path/to/software-foundation \
    https://github.com/mirage335-colossus/software-foundation.git \
    git@github.com:mirage335-colossus/software-foundation.git
EOF
}

die() {
    printf 'fork.sh: %s\n' "$*" >&2
    exit 1
}

case ${1:-} in
    -h|--help) usage; exit 0 ;;
    --) shift ;;
    -*) usage >&2; exit 2 ;;
esac
if [ "$#" -gt 0 ]; then
    destination=$1
    shift
else
    destination=$PROJECT_NAME
fi
if [ -z "$destination" ]; then
    usage >&2
    exit 2
fi

# Split only at newlines, with pathname expansion disabled: spaces, backslashes
# and shell characters remain literal. A redirected read loop would run in a
# subshell on traditional Bourne sh and lose its changes to the source arguments.
if [ "$#" -eq 0 ]; then
    saved_ifs=$IFS
    IFS='
'
    set -f
    # Deliberate field splitting using the newline-only IFS above.
    # shellcheck disable=SC2086
    set -- $DEFAULT_SOURCE_URLS
    set +f
    IFS=$saved_ifs
fi
[ "$#" -gt 0 ] || die 'DEFAULT_SOURCE_URLS must contain at least one source.'
carriage_return=`printf '\r'`
case $PROJECT_AUTHOR in
    *'
'*|*"$carriage_return"*) die 'PROJECT_AUTHOR must be a single-line name or screenname.' ;;
esac

type git >/dev/null 2>&1 || die 'Git is required.'
type mktemp >/dev/null 2>&1 || die 'mktemp is required.'

# Do not let a calling Git hook or shell redirect writes into another repository.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_COMMON_DIR GIT_NAMESPACE \
    GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_SHALLOW_FILE

case $destination in
    /*) ;;
    *) invocation_directory=`env pwd -P`
       destination="$invocation_directory/$destination" ;;
esac
# Traditional test has no -e. ls -d also detects dangling symbolic links.
if ls -d -- "$destination" >/dev/null 2>&1; then
    die "Destination already exists: $destination"
fi
parent_path=`dirname -- "$destination"`
parent=`CDPATH='' cd "$parent_path" && env pwd -P` ||
    die 'The destination parent directory must exist.'
directory_name=`basename -- "$destination"`
case $parent in
    /) destination="/$directory_name" ;;
    *) destination="$parent/$directory_name" ;;
esac
PROJECT_NAME=${PROJECT_NAME:-$directory_name}

temporary=`mktemp -d "$parent/.foundation-fork.XXXXXX"`
destination_created=false
finished=false
cleanup() {
    # An omitted action resets traps in both traditional Bourne sh and Dash.
    trap 0 1 2 15
    if [ "$destination_created" = true ] && [ "$finished" = false ]; then
        rm -rf -- "$destination"
    fi
    rm -rf -- "$temporary"
    # Let the shell retain its exit status. Traditional Bourne sh can expose
    # zero in $? here even when an explicit exit caused the failure.
}
trap cleanup 0
trap 'exit 129' 1
trap 'exit 130' 2
trap 'exit 143' 15

fetched=false
attempt=0
for source_url do
    attempt=`expr "$attempt" + 1`
    source_git="$temporary/source-$attempt.git"
    printf 'Fetching source %s of %s...\n' "$attempt" "$#" >&2
    # Keep the caller's cwd so relative local paths resolve where they were given.
    # Fetch only main at depth one, retaining its original commit ID as a baseline
    # for future updates. --no-local makes depth apply to local paths too and
    # avoids shared objects or hardlinks. Tags and other branches are not fetched.
    # Each attempt owns separate metadata so a failed source cannot leak refs.
    if git -c core.hooksPath=/dev/null clone --quiet --bare --no-local --template= \
        --depth=1 --single-branch --branch=main --no-tags \
        -- "$source_url" "$source_git" &&
        git --git-dir="$source_git" rev-parse --verify 'refs/heads/main^{commit}' >/dev/null 2>&1; then
        fetched=true
        break
    fi
    printf 'Source %s failed.\n' "$attempt" >&2
done
[ "$fetched" = true ] || die 'Could not fetch the main branch from any source URL.'
source_commit=`git --git-dir="$source_git" rev-parse --verify 'refs/heads/main^{commit}'`
source_tree=`git --git-dir="$source_git" rev-parse --verify "$source_commit^{tree}"`
git --git-dir="$source_git" ls-tree -r "$source_tree" > "$temporary/tree"
if LC_ALL=C grep -q '^160000 ' "$temporary/tree"; then
    die 'Source contains submodules; this script requires a self-contained tracked tree.'
fi

# The bare clone has its own configuration, not the source checkout's settings.
# Remove its download remote without touching main or the shallow boundary.
if git --git-dir="$source_git" config --get remote.origin.url >/dev/null; then
    git --git-dir="$source_git" config --remove-section remote.origin
fi
git --git-dir="$source_git" config core.bare false
git --git-dir="$source_git" config core.logallrefupdates true
rm -f -- "$source_git/FETCH_HEAD"
mkdir -- "$destination"
destination_created=true
mv -- "$source_git" "$destination/.git"
source_git="$destination/.git"
git -C "$destination" -c core.hooksPath=/dev/null reset --quiet --hard "$source_commit"

# Edit only recognized project attribution in regular tracked root documents.
# Read original blobs without following symlinks; leave edits out of the index.
if [ -n "$PROJECT_AUTHOR" ]; then
    project_year=`printf '%s\n' "$PROJECT_DATE" | cut -d- -f1`
    for attribution_file in LICENSE README.md; do
        entry=`git --git-dir="$source_git" ls-tree "$source_tree" -- "$attribution_file"`
        case $entry in
            '100644 blob '*|'100755 blob '*) ;;
            *) continue ;;
        esac
        git --git-dir="$source_git" show "$source_commit:$attribution_file" > "$temporary/original"
        if PROJECT_AUTHOR="$PROJECT_AUTHOR" PROJECT_YEAR="$project_year" \
            ATTRIBUTION_FILE="$attribution_file" LC_ALL=C awk '
            BEGIN { author = ENVIRON["PROJECT_AUTHOR"]; year = ENVIRON["PROJECT_YEAR"] }
            # First pass recognizes the complete foundation CC0 preamble.
            FNR == NR {
                if (FNR == 1 && $0 == "CC0 1.0 Universal") cc0 = 1
                if ($0 == "Creative Commons Legal Code") in_legal_code = 1
                if (!in_legal_code && /^Copyright [(]c[)] [0-9]+ mirage335$/) copyright_line = 1
                if (!in_legal_code && $0 == "To the extent possible under law, mirage335 has waived all copyright and") waiver = 1
                next
            }
            ENVIRON["ATTRIBUTION_FILE"] == "LICENSE" && cc0 && copyright_line && waiver {
                if ($0 == "Creative Commons Legal Code") legal_code = 1
                if (!legal_code && /^Copyright [(]c[)] [0-9]+ mirage335$/) {
                    print "Copyright (c) " year " " author; changed = 1; next
                }
                if (!legal_code && $0 == "To the extent possible under law, mirage335 has waived all copyright and") {
                    print "To the extent possible under law, " author " has waived all copyright and"; changed = 1; next
                }
            }
            ENVIRON["ATTRIBUTION_FILE"] == "README.md" &&
                $0 == "Author: mirage335. The code and documentation authored in this repository are" {
                print "Author: " author ". The code and documentation authored in this repository are"; changed = 1; next
            }
            { print }
            END { if (!changed) exit 3 }
        ' "$temporary/original" "$temporary/original" > "$temporary/attributed"; then
            cat "$temporary/attributed" > "$destination/$attribution_file"
        else
            # An unmatched document keeps its exact original bytes.
            result=$?
            [ "$result" -eq 3 ] || die "Could not update attribution in $attribution_file."
        fi
    done
fi

# Quote example arguments so names containing shell characters remain literal
# when the user copies the suggested commands. These commands are only printed.
shell_quote() {
    printf "'"
    printf '%s' "$1" | sed "s/'/'\\\\''/g"
    printf "'"
}
# Show a short path from the user's current shell directory, even when the
# destination argument was absolute. Match the shell's normal logical cd paths.
# Use external pwd because traditional shell builtins do not offer -L/-P.
suggestion_base=`env pwd -L`
relative_destination=`FORK_BASE="$suggestion_base" FORK_DESTINATION="$destination" awk '
    BEGIN {
        base = ENVIRON["FORK_BASE"]
        destination = ENVIRON["FORK_DESTINATION"]
        prefix = ""
        while (base != "/" && substr(destination, 1, length(base) + 1) != base "/") {
            sub(/\/[^/]*$/, "", base)
            if (base == "") base = "/"
            prefix = "../" prefix
        }
        if (base == "/") base = ""
        relative = prefix substr(destination, length(base) + 2)
        if (relative ~ /^-/) relative = "./" relative
        print relative
    }
'`
quoted_destination=`shell_quote "$relative_destination"`
quoted_message=`shell_quote "first commit $PROJECT_NAME $PROJECT_DATE"`

finished=true
printf '\nCreated %s in %s\nDate: %s\nBaseline: %s\nOnly main at depth one; no commit made and no remote configured.\n' \
    "$PROJECT_NAME" "$destination" "$PROJECT_DATE" "$source_commit"
printf '\nChange into your project directory, then review and commit when ready:\n'
printf 'cd %s\n' "$quoted_destination"
printf 'git status\n'
printf 'git diff\n'
printf 'git add --all\n'
printf 'git commit -m %s\n' "$quoted_message"
printf '\nSet your new repository URL, then push when ready:\n'
printf "git remote add origin 'YOUR_NEW_REPOSITORY_URL'\n"
printf 'git push -u origin main\n'
printf '\n'
