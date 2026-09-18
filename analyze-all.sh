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

run_analysis() {
    local dir="$1"
    "$SCRIPT_DIR/.venv/Scripts/python" "$SCRIPT_DIR/analyzer.py" --folder "$dir"
}

# Mappar märkta med en needs-analysis-fil analyseras, sedan raderas märkfilen.
# Ligger märkfilen i en mapp som redan har en analyzer-undermapp är den ett
# misstag – då raderas den utan att analys körs.
find "$folder" -type f -name "needs-analysis" | while read -r marker; do
    parent=$(dirname "$marker")

    if [ -d "$parent/analyzer" ]; then
        if $dry_run; then
            echo "Onödig needs-analysis i $parent raderas"
        else
            echo "Raderar onödig needs-analysis i $parent"
            rm "$marker"
        fi
        continue
    fi

    if $dry_run; then
        echo "Analys av $parent behövs (needs-analysis)"
        continue
    fi

    echo "Analyserar $parent (needs-analysis)"
    if run_analysis "$parent"; then
        rm "$marker"
    else
        echo "Analys misslyckades, behåller needs-analysis i $parent" >&2
    fi
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
        run_analysis "$parent"
    fi
done
