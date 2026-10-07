#!/bin/sh
# Container bootstrap: signed distribution mirrors and bounded APT recovery.
# Requires only the base image's shell, coreutils, sed, grep, dpkg and apt-get.
# CI_APT_ROOT is a source-configuration fixture root for offline tests; APT and
# sleep can be replaced through PATH. It is not an installation/chroot prefix.
set -eu

usage() {
    echo "usage: $0 configure | update | install PACKAGE..." >&2
    exit 2
}
[ "$#" -gt 0 ] || usage
operation=$1
shift
case "$operation" in
    configure|update) [ "$#" -eq 0 ] || usage ;;
    install) [ "$#" -gt 0 ] || usage ;;
    *) usage ;;
esac

root=${CI_APT_ROOT:-}
case "$root" in
    ''|/*) ;;
    *) echo 'CI_APT_ROOT must be an absolute fixture path' >&2; exit 2 ;;
esac
apt_dir=$root/etc/apt
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' 0
trap 'exit 130' INT
trap 'exit 143' TERM HUP

# Keep HTTP bootstrap usable before ca-certificates is installed. Existing
# HTTPS sources receive HTTPS-only mirrors, so configuration never drops TLS.
# APT continues to verify the original archive signatures and package hashes.
mirror_list() {
    list_name=$1
    list_scheme=$2
    shift 2
    list_path=$apt_dir/ci-$list_name-$list_scheme.mirrors
    : > "$list_path"
    priority=1
    for mirror in "$@"; do
        printf '%s://%s\tpriority:%s\n' "$list_scheme" "$mirror" "$priority" >> "$list_path"
        priority=$((priority + 1))
    done
    chmod 644 "$list_path"
}

map_uri() {
    uri_pattern=$1
    list_name=$2
    for scheme in http https; do
        # Escape only the replacement: URI patterns below are fixed literals.
        replacement=$(printf '%s' "mirror+file:$apt_dir/ci-$list_name-$scheme.mirrors" | sed 's/[\\&@]/\\&/g')
        mapping=$((mapping + 1))
        # Require a complete URI token, not a known URL inside a third-party
        # URI's path/query. Repeat for adjacent URIs sharing a space in deb822.
        printf ':uri%s\ns@([[:space:]])%s://%s/?([[:space:]]|$)@\\1%s\\2@g\nt uri%s\n' \
            "$mapping" "$scheme" "$uri_pattern" "$replacement" "$mapping" >> "$scratch/rewrite.sed"
    done
}

configure() {
    [ -f "$root/etc/os-release" ] || return 0
    distro=$(sed -n 's/^ID=//p' "$root/etc/os-release" | tr -d '\042\047')
    codename=$(sed -n 's/^VERSION_CODENAME=//p' "$root/etc/os-release" | tr -d '\042\047')
    architecture=$(dpkg --print-architecture)
    mkdir -p "$apt_dir/apt.conf.d"
    # Released source may still invoke apt-get directly later in the job.
    # Persist acquisition policy for those calls as well as this wrapper.
    cat > "$apt_dir/apt.conf.d/99foundation-ci" <<'APTCONFIG'
Acquire::Retries "3";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
APT::Update::Error-Mode "any";
APTCONFIG
    # Only rewrite URI fields on active APT source lines. Preserve all options,
    # suites, components, Signed-By fields and unrelated repositories verbatim.
    printf '/^[[:space:]]*(deb(-src)?[[:space:]]|URIs:[[:space:]])/ {\n' > "$scratch/rewrite.sed"
    mapping=0
    case "$distro:$architecture:$codename" in
        ubuntu:amd64:*|ubuntu:arm64:resolute)
            for scheme in http https; do
                mirror_list ubuntu "$scheme" azure.archive.ubuntu.com/ubuntu/ archive.ubuntu.com/ubuntu/ security.ubuntu.com/ubuntu/
            done
            map_uri 'archive\.ubuntu\.com/ubuntu' ubuntu
            map_uri 'security\.ubuntu\.com/ubuntu' ubuntu
            map_uri 'azure\.archive\.ubuntu\.com/ubuntu' ubuntu
            echo 'APT: prefer the Azure Ubuntu mirror with archive/security fallback.'
            ;;
        ubuntu:*)
            # Older arm64 and other ports architectures require ports mirrors.
            # Do not guess that the primary/Azure archive serves their suites.
            echo 'APT: preserving Ubuntu ports/other architecture sources.'
            ;;
        debian:*)
            for scheme in http https; do
                mirror_list debian "$scheme" deb.debian.org/debian/ ftp.debian.org/debian/
                mirror_list debian-security "$scheme" deb.debian.org/debian-security/ security.debian.org/debian-security/
            done
            map_uri 'deb\.debian\.org/debian-security' debian-security
            map_uri 'security\.debian\.org/debian-security' debian-security
            map_uri 'deb\.debian\.org/debian' debian
            map_uri 'ftp\.debian\.org/debian' debian
            echo 'APT: prefer the Debian CDN with separate archive/security fallback.'
            ;;
        *) echo "APT: preserving sources for $distro." ;;
    esac
    printf '}\n' >> "$scratch/rewrite.sed"
    for source in "$apt_dir/sources.list" "$apt_dir"/sources.list.d/*.list "$apt_dir"/sources.list.d/*.sources; do
        [ -f "$source" ] || continue
        sed -i -E -f "$scratch/rewrite.sed" "$source"
    done
}

run_apt() {
    if [ "$attempt" -gt 1 ]; then
        # Revalidate retry metadata even through an intermediary cache.
        set -- -o Acquire::http::No-Cache=true -o Acquire::https::No-Cache=true "$@"
    fi
    # A pipeline keeps installation progress visible while preserving APT's
    # status in POSIX sh, which has no portable pipefail option.
    {
        apt_result=0
        LC_ALL=C apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 \
            -o Acquire::https::Timeout=30 -o APT::Update::Error-Mode=any "$@" || apt_result=$?
        printf '%s\n' "$apt_result" > "$scratch/status"
    } 2>&1 | tee "$scratch/apt.log"
    apt_result=$(cat "$scratch/status")
    return "$apt_result"
}

fetch_failure() {
    # Never recover authentication, repository policy, package resolution or
    # dpkg failures by retrying them. Unknown failures also remain fatal.
    if grep -Eiq 'NO_PUBKEY|BADSIG|EXPKEYSIG|signature|not signed|not authenticated|unauthenticated|does not have a Release file|Release file.*(expired|not valid)|certificate verification|Certificate verification|Hash Sum mismatch|Hashes of expected file|unexpected size|dpkg:|Sub-process .*/dpkg|unmet dependencies|Unable to locate package|has no installation candidate|held broken packages' "$scratch/apt.log"; then
        return 1
    fi
    grep -Eiq '(Failed to fetch|Failed to download|Unable to fetch).*(404|408|429|500|502|503|504|Not Found|timed out|Timeout|Temporary failure|Could not resolve|Could not connect|Unable to connect|Connection|Network is unreachable|TLS connection|TLS handshake)|Temporary failure resolving|Could not resolve|Could not connect|Unable to connect|Connection (failed|timed out|reset|refused)|Network is unreachable' "$scratch/apt.log"
}

configure
[ "$operation" != configure ] || exit 0
attempt=1
while :; do
    echo "APT: $operation attempt $attempt/3 (fresh strict package indexes)."
    result=0
    if run_apt update; then
        if [ "$operation" = update ]; then exit 0; fi
        run_apt install -y --no-install-recommends "$@" || result=$?
    else
        result=$?
    fi
    [ "$result" -ne 0 ] || exit 0
    if ! fetch_failure; then
        echo 'APT: non-fetch failure; refusing to retry.' >&2
        exit "$result"
    fi
    if [ "$attempt" -ge 3 ]; then
        echo 'APT: fetch recovery exhausted after 3 attempts.' >&2
        exit "$result"
    fi
    delay=5
    [ "$attempt" -lt 2 ] || delay=15
    echo "::warning::APT fetch failed; refreshing indexes and retrying in $delay seconds."
    sleep "$delay"
    attempt=$((attempt + 1))
done
