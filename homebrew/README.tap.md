# Ghost Chimera Homebrew tap

Ships `brew install ghostchimera` without waiting on Homebrew core.

## Create the tap (one time, ~5 minutes)

```bash
# 1. New public repo: github.com/fernandogarzaaa/homebrew-ghostchimera
gh repo create fernandogarzaaa/homebrew-ghostchimera --public \
  --description "Homebrew tap for Ghost Chimera"

# 2. Copy the formula in (from a tagged GHOST-Chimera checkout):
cp homebrew/ghostchimera.rb /tmp/tap/Formula/ghostchimera.rb
cd /tmp/tap && git add . && git commit -m "ghostchimera 0.4.0" && git push -u origin main
```

## Install (users)

```bash
brew tap fernandogarzaaa/ghostchimera
brew install ghostchimera
ghostchimera doctor
```

## Per release

1. Publish the GitHub Release (`publish.yml` uploads the sdist + wheel to PyPI
   and attaches them to the release).
2. Point `url` in `Formula/ghostchimera.rb` at the new PyPI sdist and update
   `sha256` (`curl -sL <url> | shasum -a 256`).
3. `brew audit --new ghostchimera && brew test ghostchimera`, then push.

Optional extras after install: the formula's venv is isolated; add backends with
its Python, pinned to the installed version, e.g.
`$(brew --prefix)/opt/ghostchimera/libexec/bin/python -m pip install "ghostchimera[desktop,mcp]==0.4.0b1"`.
