#!/bin/sh
set -e
if [ $# -lt 4 ]; then
    echo "usage: $0 ROM STATE OUTPUT_DIR DRIVER_SCRIPT [ARTWORK_PRODUCT ARTWORK_DIR]" >&2
    exit 2
fi
ROM=$1; STATE=$2; OUTPUT=$3; DRIVER=$4; ARTWORK_PRODUCT=$5; ARTWORK_DIR=$6
REPO=$(cd "$(dirname "$0")/../.." && pwd)
VELO_EMU=${VELO_EMU:-$REPO/../velo-emu}
mkdir -p "$OUTPUT"
PORT=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
(cd "$VELO_EMU" && exec ./headless "$ROM" --load="$STATE" --seconds=100000 --realtime=1 --tcp=$PORT > "$OUTPUT/headless.log" 2>&1) &
EMULATOR=$!
trap 'kill $EMULATOR 2>/dev/null' EXIT INT TERM HUP ALRM
sleep 1
HOME_DIR="$OUTPUT/home"
rm -rf "$HOME_DIR"
mkdir -p "$HOME_DIR/artwork"
if [ -n "$ARTWORK_PRODUCT" ] && [ -n "$ARTWORK_DIR" ]; then
    ln -s "$ARTWORK_DIR" "$HOME_DIR/artwork/$ARTWORK_PRODUCT"
fi
if [ -n "$CLASSICSYNC_LOCALE_DIR" ]; then
    ln -s "$CLASSICSYNC_LOCALE_DIR" "$HOME_DIR/locale"
fi
CLASSICSYNC_HOME="$HOME_DIR" "$REPO/.venv/bin/python" "$DRIVER" "tcp:127.0.0.1:$PORT" "$OUTPUT"
