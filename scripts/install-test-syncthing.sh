#!/bin/sh
# Verified upstream fixture; CI runs only on linux/amd64.
set -eu
fixture_dir=${1:?fixture directory required}
mkdir -p "$fixture_dir"
curl --fail --silent --show-error --location --retry 3 \
  https://github.com/syncthing/syncthing/releases/download/v2.1.5/syncthing-linux-amd64-v2.1.5.tar.gz \
  --output "$fixture_dir/syncthing.tar.gz"
printf '%s  %s\n' 3d222b609f7ab2944e02748cb10488b4160d446b49e0eafc107ef2a525ab3486 "$fixture_dir/syncthing.tar.gz" | sha256sum --check --status
tar -xzf "$fixture_dir/syncthing.tar.gz" -C "$fixture_dir"
