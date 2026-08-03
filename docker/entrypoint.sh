#!/bin/sh
set -eu

if [ "${REW_TWOGIS_BROWSER_HEADLESS:-false}" = "false" ]; then
    Xvfb :99 -screen 0 1280x720x24 -nolisten tcp -ac &
    export DISPLAY=:99
fi

alembic upgrade head
exec "$@"
