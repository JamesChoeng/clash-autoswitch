#!/bin/sh
# clashpilot bootstrap installer (macOS / Linux).
#
# Makes the environment self-sufficient before installing clashpilot:
#   1. detect Python >= 3.8; install it if missing (brew / apt / dnf / pacman / zypper / apk)
#   2. detect git;  install it if missing
#   3. ensure pipx
#   4. pipx install clashpilot
#
# Run it without cloning anything:
#   curl -fsSL https://raw.githubusercontent.com/JamesChoeng/clashpilot/main/install.sh | sh
#
# Env overrides:
#   CLASHPILOT_REPO - source to install from (default: the GitHub repo)
set -eu

REPO_URL="${CLASHPILOT_REPO:-git+https://github.com/JamesChoeng/clashpilot.git}"
MIN_MAJOR=3
MIN_MINOR=8

step() { printf '\033[36m==> %s\033[0m\n' "$1"; }
note() { printf '    %s\n' "$1"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$1" >&2; }
die()  { printf '\033[31merror: %s\033[0m\n' "$1" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# Echo the first python on PATH that satisfies the minimum version, else nothing.
find_python() {
    for cand in python3 python; do
        have "$cand" || continue
        if "$cand" -c "import sys; sys.exit(0 if sys.version_info[:2] >= ($MIN_MAJOR, $MIN_MINOR) else 1)" 2>/dev/null; then
            command -v "$cand"
            return 0
        fi
    done
    return 1
}

# sudo only when we're not already root and sudo exists.
SUDO=""
if [ "$(id -u 2>/dev/null || echo 0)" != "0" ] && have sudo; then
    SUDO="sudo"
fi

pkg_install() {
    # pkg_install <brew-name> <apt/...-name>
    if have brew; then
        note "brew install $1"; brew install "$1"; return $?
    elif have apt-get; then
        note "apt-get install $2"; $SUDO apt-get update -y && $SUDO apt-get install -y $2; return $?
    elif have dnf; then
        note "dnf install $2"; $SUDO dnf install -y $2; return $?
    elif have yum; then
        note "yum install $2"; $SUDO yum install -y $2; return $?
    elif have pacman; then
        note "pacman -S $2"; $SUDO pacman -Sy --noconfirm $2; return $?
    elif have zypper; then
        note "zypper install $2"; $SUDO zypper install -y $2; return $?
    elif have apk; then
        note "apk add $2"; $SUDO apk add $2; return $?
    fi
    return 127
}

install_python() {
    step "Python >= $MIN_MAJOR.$MIN_MINOR not found - installing"
    if [ "$(uname -s)" = "Darwin" ] && ! have brew; then
        die "Homebrew not found. Install it from https://brew.sh and re-run (or install Python from https://www.python.org/downloads/)."
    fi
    # apt names the venv/pip extras separately; install them too where relevant.
    if have apt-get; then
        pkg_install python3 "python3 python3-venv python3-pip" || die "failed to install Python via apt-get"
    else
        pkg_install python3 python3 || die "could not auto-install Python with a known package manager. Install Python 3.8+ from https://www.python.org/downloads/ and re-run."
    fi
}

install_git() {
    step "git not found - installing"
    pkg_install git git || die "could not auto-install git. Install it from https://git-scm.com/downloads and re-run."
}

# --- Main --------------------------------------------------------------------

PY="$(find_python || true)"
if [ -z "$PY" ]; then
    install_python
    PY="$(find_python || true)"
    [ -n "$PY" ] || die "Python install completed but no usable interpreter was found"
fi
step "Using $("$PY" -V 2>&1) ($PY)"

have git || install_git

step "Ensuring pipx"
if have pipx; then
    :
elif "$PY" -m pipx --version >/dev/null 2>&1; then
    :
else
    "$PY" -m pip install --user --upgrade pip pipx 2>/dev/null \
        || die "could not install pipx. On Debian/Ubuntu try: $SUDO apt-get install -y pipx"
fi
"$PY" -m pipx ensurepath >/dev/null 2>&1 || true

step "Installing clashpilot from $REPO_URL"
"$PY" -m pipx install --force "$REPO_URL"

printf '\n'
step "Done. Open a new shell (or 'source ~/.profile'), then run:  clashpilot up"
