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

1. Tag `vX.Y.Z` in GHOST-Chimera.
2. Update `url` + `sha256` in `Formula/ghostchimera.rb`
   (`shasum -a 256 vX.Y.Z.tar.gz` from the release page).
3. `brew audit --new ghostchimera && brew test ghostchimera`, then push.

Optional extras after install: `$(brew --prefix)/opt/...` venvs are isolated;
add backends with the venv's pip, e.g.
`.../libexec/bin/pip install "ghostchimera[desktop,mcp]"`.
