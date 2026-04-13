#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
folder="."
dry_run=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --folder)
            folder="$2"
            shift 2
            ;;
        --dry-run)
            dry_run=true
            shift
            ;;
        *)
            echo "Okänd flagga: $1" >&2
            exit 1
            ;;
    esac
done

find "$folder" -iname "processed_files.json" | while read -r file; do
    json_timestamp=$(stat -c "%Y" "$file")
    parent=$(dirname "$(dirname "$file")")

    newest_epoch=$(find "$parent" -maxdepth 1 -type f \
        | xargs stat -c "%Y" 2>/dev/null \
        | sort -n | tail -1)

    [ -z "$newest_epoch" ] && continue
    [ "$newest_epoch" -le "$json_timestamp" ] && continue

    if $dry_run; then
        echo "Analys av $parent behövs"
    else
        echo "Analyserar $parent"
        "$SCRIPT_DIR/.venv/Scripts/python" "$SCRIPT_DIR/analyzer.py" --folder "$parent"
    fi
done
