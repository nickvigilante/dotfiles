# Shell utility functions — cross-platform.

# Create a directory and cd into it immediately.
mkcd() {
    mkdir -p "$1" && cd "$1"
}

# Search running processes.
psg() {
    ps aux | grep -i "$1" | grep -v grep
}

# Extract archives — auto-detects format.
extract() {
    if [[ ! -f "$1" ]]; then
        echo "'$1' is not a valid file"
        return 1
    fi
    case "$1" in
        *.tar.bz2)  tar xjf "$1"        ;;
        *.tar.gz)   tar xzf "$1"        ;;
        *.tar.xz)   tar xJf "$1"        ;;
        *.tar.zst)  tar --zstd -xf "$1" ;;
        *.bz2)      bunzip2 "$1"        ;;
        *.gz)       gunzip "$1"         ;;
        *.tar)      tar xf "$1"         ;;
        *.tbz2)     tar xjf "$1"        ;;
        *.tgz)      tar xzf "$1"        ;;
        *.zip)      unzip "$1"          ;;
        *.Z)        uncompress "$1"     ;;
        *.7z)       7z x "$1"           ;;
        *.rar)      unrar x "$1"        ;;
        *)          echo "'$1' cannot be extracted by extract()" ;;
    esac
}

# Print PATH entries one per line.
path() {
    echo "$PATH" | tr ':' '\n'
}

# Start a quick HTTP server in the current directory.
serve() {
    local port="${1:-8000}"
    echo "Serving at http://localhost:$port"
    python3 -m http.server "$port"
}

# Find files by name (case-insensitive).
ff() {
    find . -iname "*$1*" 2>/dev/null
}

# Show disk usage of top-level items, sorted by size.
dusage() {
    du -sh ./* 2>/dev/null | sort -h
}

# Jump to a git repo root.
groot() {
    local root
    root=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "Not in a git repo."; return 1; }
    cd "$root"
}

# Quickly create and activate a uv venv in the current directory.
venv-here() {
    uv venv .venv
    source .venv/bin/activate
}
