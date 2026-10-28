#!/usr/bin/env bash
# Desktop side: build every bundle a remote headless worker needs and copy it to <host>:C:/civ5/incoming/.
#
#   bash .claude/skills/headless-remote-setup/scripts/pack.sh <ssh-alias> [out-dir]
#
# Bundles (about 270 MB in all):
#   civ5-game-subset.tar   the game's root DLLs, Locale/ (ICU data) and Assets/ without art, audio and video
#   civ5-headless-*.zip    c5h release kit (host exe, python package, profiles, probes) from the local checkout
#   pinned.tar             pinned/vp-modpack-<ver>/ (game DB + merged localization) and pinned/specs/
#   toolkit.tar            this repository's tracked and untracked-not-ignored files (working tree, not HEAD)
#   vcredist_x86.exe       VC++ 2008 runtime the host and the Firaxis DLLs need (Steam's copy)
#   uv.exe                 this desktop's uv
#   remote-install.ps1     the remote half
set -euo pipefail

HOST="${1:?usage: pack.sh <ssh-alias> [out-dir]}"
OUT="${2:-${TMPDIR:-/tmp}/civ5-remote-pack}"
PINNED_VERSION="${PINNED_VERSION:-5.4.8}"
GAME_PARENT="/c/Program Files (x86)/Steam/steamapps/common"
GAME="Sid Meier's Civilization V"
C5H="${C5H_DIR:-$HOME/Documents/civ5-headless}"
UV="${UV_EXE:-$HOME/AppData/Roaming/Python/Python311/Scripts/uv.exe}"
VCREDIST="$GAME_PARENT/Steamworks Shared/_CommonRedist/vcredist/2008/vcredist_x86.exe"
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Write tar/zip outputs to a POSIX path: GNU tar reads "C:/..." as a remote host.
mkdir -p "$OUT/kit"
OUT="$(cd "$OUT" && pwd)"

echo "== game subset"
excludes=()
for e in ogg dds mp3 wmv wav tga wma gr2 binka bik pdb psd ani png bmp; do
  excludes+=("--exclude=*.$e" "--exclude=*.${e^^}")
done
(cd "$GAME_PARENT" && tar -cf "$OUT/civ5-game-subset.tar" "${excludes[@]}" \
  "$GAME/Assets" "$GAME/Locale" "$GAME"/*.dll)

echo "== c5h kit (--worktree: the exe carries the modpack-vfs-tiebreak fix built from a dirty tree)"
rm -f "$OUT"/kit/*.zip
(cd "$C5H" && python tools/make_kit.py --worktree --python none --out "$OUT/kit" > "$OUT/kit/make_kit.json")

echo "== pinned database"
(cd "$C5H" && tar -cf "$OUT/pinned.tar" "pinned/vp-modpack-$PINNED_VERSION" pinned/specs)

echo "== toolkit"
(cd "$REPO" && git ls-files -co --exclude-standard > "$OUT/toolkit-files.txt" \
  && tar -cf "$OUT/toolkit.tar" -T "$OUT/toolkit-files.txt")

ls -la "$OUT" "$OUT/kit"
echo "== copy to $HOST"
ssh "$HOST" 'New-Item -ItemType Directory -Force C:\civ5\incoming | Out-Null'
scp -q "$OUT/civ5-game-subset.tar" "$OUT/pinned.tar" "$OUT/toolkit.tar" "$OUT"/kit/*.zip \
  "$VCREDIST" "$UV" "$HERE/remote-install.ps1" "$HOST:C:/civ5/incoming/"
ssh "$HOST" 'Get-ChildItem C:\civ5\incoming | Select-Object Name, Length | Format-Table -AutoSize'
