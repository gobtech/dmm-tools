#!/bin/bash
# batch_generate.sh
# Processes all artists defined in artists.json and generates reports
#
# Usage:
#   ./batch_generate.sh                     # Process all artists
#   ./batch_generate.sh --artist "Djo"      # Process single artist
#   ./batch_generate.sh --output-dir ./out  # Custom output directory

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${SCRIPT_DIR}/artists.json"
OUTPUT_DIR="${SCRIPT_DIR}/reports"

# Parse arguments
FILTER_ARTIST=""
while [[ $# -gt 0 ]]; do
  case $1 in
    --artist) FILTER_ARTIST="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Check dependencies
if ! command -v node &> /dev/null; then
  echo "Error: Node.js is required"
  exit 1
fi

if ! node -e "require('docx')" 2>/dev/null; then
  echo "Installing docx package..."
  npm install -g docx
fi

# Check config
if [ ! -f "$CONFIG" ]; then
  echo "Error: Config file not found: $CONFIG"
  echo ""
  echo "Create artists.json with this format:"
  echo '['
  echo '  {'
  echo '    "name": "Djo",'
  echo '    "input_dir": "./data/djo/"'
  echo '  },'
  echo '  {'
  echo '    "name": "Tame Impala",'
  echo '    "input_dir": "./data/tame-impala/"'
  echo '  }'
  echo ']'
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Process artists
ARTISTS=$(cat "$CONFIG")
COUNT=$(echo "$ARTISTS" | node -e "const d=require('fs').readFileSync('/dev/stdin','utf8'); console.log(JSON.parse(d).length)")

echo "======================================="
echo "  Airplay Report Generator"
echo "======================================="
echo ""

PROCESSED=0
ERRORS=0

for i in $(seq 0 $((COUNT - 1))); do
  NAME=$(echo "$ARTISTS" | node -e "const d=require('fs').readFileSync('/dev/stdin','utf8'); console.log(JSON.parse(d)[$i].name)")
  INPUT=$(echo "$ARTISTS" | node -e "const d=require('fs').readFileSync('/dev/stdin','utf8'); console.log(JSON.parse(d)[$i].input_dir || '')")
  FILES=$(echo "$ARTISTS" | node -e "const d=require('fs').readFileSync('/dev/stdin','utf8'); console.log(JSON.parse(d)[$i].files || '')")

  # Filter if --artist specified
  if [ -n "$FILTER_ARTIST" ] && [ "$NAME" != "$FILTER_ARTIST" ]; then
    continue
  fi

  SAFE_NAME=$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g')
  OUTPUT_FILE="${OUTPUT_DIR}/${SAFE_NAME}_radio_plays_28d.docx"

  echo "Processing: $NAME"

  CMD="node ${SCRIPT_DIR}/generate_report.js --artist \"$NAME\" --output \"$OUTPUT_FILE\""
  if [ -n "$INPUT" ]; then
    CMD="$CMD --input \"$INPUT\""
  elif [ -n "$FILES" ]; then
    CMD="$CMD --files \"$FILES\""
  else
    echo "  Error: No input_dir or files specified for $NAME"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  if eval $CMD; then
    PROCESSED=$((PROCESSED + 1))
  else
    echo "  Error processing $NAME"
    ERRORS=$((ERRORS + 1))
  fi
  echo ""
done

echo "======================================="
echo "  Done: $PROCESSED processed, $ERRORS errors"
echo "  Output: $OUTPUT_DIR/"
echo "======================================="
