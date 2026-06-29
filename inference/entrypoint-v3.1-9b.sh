#!/bin/bash
# Compatibility wrapper. The active runtime is model-neutral.
exec "$(dirname "$0")/entrypoint-v3.1.sh" "$@"
