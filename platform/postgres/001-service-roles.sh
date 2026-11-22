#!/bin/sh
set -eu
# Postgres sources non-executable init scripts. Return to its entrypoint after
# provisioning, even when a bind mount does not preserve the executable bit.
sh /setup/provision.sh
