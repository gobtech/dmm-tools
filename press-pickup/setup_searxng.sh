#!/bin/bash
# SearXNG Setup for DMM Tools
# Replaces Brave Search API with self-hosted SearXNG metasearch engine
#
# Usage:
#   ./setup_searxng.sh          # Start SearXNG
#   ./setup_searxng.sh stop     # Stop SearXNG
#   ./setup_searxng.sh status   # Check if running
#   ./setup_searxng.sh restart  # Restart SearXNG

set -e

CONTAINER_NAME="searxng"
PORT=8888
IMAGE="searxng/searxng"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETTINGS_FILE="${SCRIPT_DIR}/searxng_settings.yml"

case "${1:-start}" in
  start)
    # Check if already running
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
      echo "SearXNG is already running on port ${PORT}"
      exit 0
    fi

    # Remove stopped container if it exists
    docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true

    echo "Starting SearXNG on port ${PORT}..."
    docker run -d \
      --name "${CONTAINER_NAME}" \
      -p "${PORT}:8080" \
      -v "${SETTINGS_FILE}:/etc/searxng/settings.yml:ro" \
      --restart unless-stopped \
      "${IMAGE}"

    # Wait for it to be ready
    echo -n "Waiting for SearXNG to start"
    for i in $(seq 1 30); do
      if curl -sf "http://localhost:${PORT}/search?q=test&format=json" > /dev/null 2>&1; then
        echo " ready!"
        echo "SearXNG is running at http://localhost:${PORT}"
        exit 0
      fi
      echo -n "."
      sleep 1
    done
    echo " timeout — check docker logs ${CONTAINER_NAME}"
    exit 1
    ;;

  stop)
    echo "Stopping SearXNG..."
    docker stop "${CONTAINER_NAME}" 2>/dev/null && echo "Stopped." || echo "Not running."
    docker rm "${CONTAINER_NAME}" 2>/dev/null || true
    ;;

  restart)
    "$0" stop
    "$0" start
    ;;

  status)
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
      echo "SearXNG is running on port ${PORT}"
      # Health check
      if curl -sf "http://localhost:${PORT}/search?q=test&format=json" > /dev/null 2>&1; then
        echo "Health check: OK"
      else
        echo "Health check: FAILED (container running but not responding)"
      fi
    else
      echo "SearXNG is not running"
    fi
    ;;

  *)
    echo "Usage: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac
