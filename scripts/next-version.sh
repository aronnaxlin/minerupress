#!/usr/bin/env bash
# Print the version to release for a commit, or nothing when there is nothing
# new to release. Versions live in git tags (vX.Y.Z); every release bumps the
# patch of the highest existing tag.
#
# Usage: scripts/next-version.sh [commit]   (default: HEAD)
set -euo pipefail

commit="${1:-HEAD}"

# Opt out of a release from the commit subject (the first line only, so a body
# that merely mentions the marker does not count).
if git log -1 --format=%s "$commit" | grep -qiF '[skip release]'; then
  exit 0
fi

latest="$(git tag --list 'v[0-9]*' --sort=-v:refname | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n1 || true)"

if [ -z "$latest" ]; then
  echo "0.0.1"
  exit 0
fi

# Already released: the latest tag is this commit or contains everything after it.
if [ "$(git rev-list --count "$latest..$commit")" -eq 0 ]; then
  exit 0
fi

IFS=. read -r major minor patch <<<"${latest#v}"
echo "$major.$minor.$((patch + 1))"
