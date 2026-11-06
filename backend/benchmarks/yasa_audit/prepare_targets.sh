#!/usr/bin/env bash
# Download and assemble the benchmark targets. Third-party code is not committed to this repo.
#
#   bash backend/benchmarks/yasa_audit/prepare_targets.sh /path/to/targets
#
# Produces:
#   <dest>/juice       OWASP Juice Shop backend at commit 717f5ef (MIT): routes, lib, models, data, server.ts
#   <dest>/juice-mini  21 route files + lib/models/data, with the trimmed server.ts from this directory
#   <dest>/hms         projectworlds Hospital-Management-System (Java Servlet + JSP), vendored assets removed
set -euo pipefail

DEST="${1:?usage: prepare_targets.sh <dest-dir>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
JUICE_COMMIT="717f5efa886b0417eeecb52378b03cf10567b7e2"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$DEST"

# ---- Juice Shop ----
git -C "$WORK" init -q juice-src
git -C "$WORK/juice-src" fetch -q --depth 1 https://github.com/juice-shop/juice-shop.git "$JUICE_COMMIT" \
  || git -C "$WORK/juice-src" fetch -q --depth 50 https://github.com/juice-shop/juice-shop.git master
git -C "$WORK/juice-src" checkout -q "$JUICE_COMMIT" 2>/dev/null || git -C "$WORK/juice-src" checkout -q FETCH_HEAD
J="$WORK/juice-src"

rm -rf "$DEST/juice" && mkdir -p "$DEST/juice/data"
cp -r "$J/routes" "$J/lib" "$J/models" "$J/server.ts" "$J/app.ts" "$J/tsconfig.json" "$J/package.json" "$DEST/juice/"
cp "$J"/data/*.ts "$DEST/juice/data/"

rm -rf "$DEST/juice-mini" && mkdir -p "$DEST/juice-mini/routes"
cp -r "$DEST/juice/lib" "$DEST/juice/models" "$DEST/juice/data" "$DEST/juice/tsconfig.json" "$DEST/juice/package.json" "$DEST/juice-mini/"
for r in login search updateProductReviews likeProductReviews showProductReviews redirect trackOrder b2bOrder \
         userProfile updateUserProfile fileUpload profileImageUrlUpload dataErasure fileServer keyServer \
         logfileServer quarantineServer captcha basket address delivery; do
  cp "$DEST/juice/routes/$r.ts" "$DEST/juice-mini/routes/"
done
cp "$HERE/juice-mini/server.ts" "$DEST/juice-mini/server.ts"
# directories served by /ftp, /encryptionkeys and /support/logs (access-control benchmark)
for d in ftp encryptionkeys; do cp -r "$J/$d" "$DEST/juice/$d"; cp -r "$J/$d" "$DEST/juice-mini/$d"; done
mkdir -p "$DEST/juice/logs" "$DEST/juice-mini/logs"

# ---- HMS ----
curl -fsSL -o "$WORK/hms.zip" https://projectworlds.com/wp-content/uploads/2021/05/Hospital-Management-System.zip
unzip -q "$WORK/hms.zip" -d "$WORK/hms"
rm -rf "$DEST/hms"
cp -r "$WORK/hms/Hospital-Management-System/HospDBMS" "$DEST/hms"
rm -rf "$DEST/hms/build" "$DEST/hms/WebContent/master" "$DEST/hms/WebContent/vendor"
find "$DEST/hms" -type f \( -name '*.js' -o -name '*.css' -o -name '*.map' -o -name '*.scss' -o -name '*.woff*' \
  -o -name '*.ttf' -o -name '*.eot' -o -name '*.svg' -o -name '*.png' -o -name '*.jpg' -o -name '*.gif' \
  -o -name '*.jar' -o -name '*.class' \) -delete

echo "targets ready in $DEST: juice, juice-mini, hms"
