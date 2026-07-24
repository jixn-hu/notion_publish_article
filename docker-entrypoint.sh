#!/bin/sh
set -eu

if [ ! -f /app/data/publisher.db ] && [ -f /app/import/publisher.db ]; then
    echo "Importing existing publisher.db into the Docker volume..."
    cp /app/import/publisher.db /app/data/publisher.db
fi

exec "$@"
