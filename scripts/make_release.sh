#!/usr/bin/env bash
# Package downloadable release bundles for macOS and Windows.
#
#   ./scripts/make_release.sh v0.29.0
#
# Produces dist-release/video-studio-<version>-{macos,windows}.zip plus
# SHA256SUMS.txt. Run automatically by .github/workflows/release.yml when a
# v* tag is pushed — see docs/ops.md "Releases".
#
# The bundle is `git archive` of HEAD (tracked files ONLY — .env, local
# databases and node_modules can never leak into a release) plus the
# prebuilt control panel in web/dist: the API serves the SPA itself when
# web/dist exists, so a release user needs Python + Docker but NOT Node.
set -euo pipefail

VERSION="${1:?usage: make_release.sh vX.Y.Z}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist-release"
NAME="video-studio-$VERSION"
STAGE="$OUT/stage/$NAME"

rm -rf "$OUT/stage"
mkdir -p "$STAGE"

echo "==> staging tracked files ($VERSION)"
git -C "$ROOT" archive HEAD | tar -x -C "$STAGE"

echo "==> bundling the prebuilt control panel"
if [ ! -d "$ROOT/web/dist" ]; then
  (cd "$ROOT/web" && npm ci && npm run build)
fi
rm -rf "$STAGE/web/dist"
cp -R "$ROOT/web/dist" "$STAGE/web/dist"
printf '%s\n' "$VERSION" > "$STAGE/VERSION"

for platform in macos windows; do
  echo "==> packaging $platform"
  cp "$ROOT/scripts/release/GETTING-STARTED-$platform.txt" "$STAGE/GETTING-STARTED.txt"
  rm -f "$OUT/$NAME-$platform.zip"
  (cd "$OUT/stage" && zip -qr "$OUT/$NAME-$platform.zip" "$NAME")
done

rm -rf "$OUT/stage"

echo "==> checksums"
(cd "$OUT" && python3 - <<'PY'
import hashlib, pathlib

lines = []
for path in sorted(pathlib.Path(".").glob("*.zip")):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lines.append(f"{digest}  {path.name}")
pathlib.Path("SHA256SUMS.txt").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
PY
)

echo "done: $OUT"
