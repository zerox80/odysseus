#!/usr/bin/env bash
# Build patched wheels for Real-ESRGAN's unmaintained dependencies.
#
# basicsr / gfpgan / facexlib (xinntao, last released 2022) read their version
# in setup.py with:
#
#     exec(compile(f.read(), version_file, 'exec'))
#     return locals()['__version__']
#
# Python 3.13+ implements PEP 667: locals() inside a function returns an
# independent snapshot that exec() can no longer mutate, so the read raises
# `KeyError: '__version__'` and the sdist build fails. That is why the Cookbook
# "install realesrgan" button dies on the python:3.14 image. The packages have
# no fixed release, so we patch get_version() to exec into an explicit namespace
# dict (works on every Python) and build wheels from the patched source.
#
# Usage: build-realesrgan-wheels.sh [OUTPUT_DIR]   (default: /wheels)
set -euo pipefail

OUT="${1:-/wheels}"
mkdir -p "$OUT"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

# Pinned to the versions Real-ESRGAN 0.3.0 resolves to.
SPECS="basicsr==1.4.2 gfpgan==1.3.8 facexlib==0.3.0"

for spec in $SPECS; do
  name="${spec%%==*}"
  ver="${spec##*==}"
  # pip download builds metadata (and trips the same bug), so use the raw
  # sdists. Both URL and digest are intentionally committed: querying PyPI
  # metadata at build time would let a compromised index change both values.
  case "$spec" in
    basicsr==1.4.2)
      url="https://files.pythonhosted.org/packages/86/41/00a6b000f222f0fa4c6d9e1d6dcc9811a374cabb8abb9d408b77de39648c/basicsr-1.4.2.tar.gz"
      sha256="b89b595a87ef964cda9913b4d99380ddb6554c965577c0c10cb7b78e31301e87"
      ;;
    gfpgan==1.3.8)
      url="https://files.pythonhosted.org/packages/6b/e9/b2db24ed840f188792581d217229022ff85e0ae3055a708e9f28430b8083/gfpgan-1.3.8.tar.gz"
      sha256="21618b06ce8ea6230448cb526b012004f23a9ab956b55c833f69b9fc8a60c4f9"
      ;;
    facexlib==0.3.0)
      url="https://files.pythonhosted.org/packages/e1/93/c820cd2c6315b635934770808e0b01ed4db257ec33bcf803909dcf4bce15/facexlib-0.3.0.tar.gz"
      sha256="7ae784a520eb52e05583e8bf9f68f77f45083239ac754d646d635017b49e7763"
      ;;
    *)
      echo "missing pinned sdist metadata for ${spec}" >&2
      exit 1
      ;;
  esac
  echo ">> fetching ${name} ${ver}: ${url}"
  curl -fsSL "$url" -o "${name}.tar.gz"
  echo "${sha256}  ${name}.tar.gz" | sha256sum -c -
  tar xzf "${name}.tar.gz"
done

echo ">> patching get_version()"
python - <<'PY'
import pathlib
old_exec = "exec(compile(f.read(), version_file, 'exec'))"
new_exec = "_ver_ns = {}\n        exec(compile(f.read(), version_file, 'exec'), _ver_ns)"
old_ret = "return locals()['__version__']"
new_ret = "return _ver_ns['__version__']"
patched = 0
for setup in pathlib.Path(".").glob("*/setup.py"):
    s = setup.read_text()
    if old_exec in s and old_ret in s:
        setup.write_text(s.replace(old_exec, new_exec).replace(old_ret, new_ret))
        print("   patched", setup)
        patched += 1
assert patched == 3, f"expected to patch 3 setup.py files, patched {patched}"
PY

echo ">> building wheels into ${OUT}"
pip wheel --no-build-isolation --no-deps -w "$OUT" ./basicsr-* ./gfpgan-* ./facexlib-*
ls -l "$OUT"
