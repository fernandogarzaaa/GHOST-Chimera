# Homebrew formula for Ghost Chimera (tap distribution).
#
# Upstream Homebrew core admission is out of scope; ship via a tap:
#   brew tap fernandogarzaaa/ghostchimera
#   brew install ghostchimera
# See homebrew/README.tap.md for the 5-minute tap setup.
#
# Maintainer release checklist:
#   1. Tag vX.Y.Z on GitHub, note the tarball SHA256 below.
#   2. python -m build && twine upload dist/*
#   3. `brew audit --new ghostchimera` and `brew test ghostchimera` before tap push.
class Ghostchimera < Formula
  desc "Background AI infrastructure: ambient intelligence runtime for AI agents"
  homepage "https://github.com/fernandogarzaaa/GHOST-Chimera"
  # RELEASE: replace version + sha256 for every tagged release.
  url "https://github.com/fernandogarzaaa/GHOST-Chimera/archive/refs/tags/v0.4.0.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_TARBALL_SHA256"
  license "MIT"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
    # Best-effort full install: every optional backend, one extra at a time,
    # so a heavy platform-specific extra (torch/CUDA/GUI) can fail without
    # breaking the whole install. Core always works; `doctor` reports the rest.
    %w[desktop mcp gateway local quantum minimind voice].each do |extra|
      system libexec/"bin"/"pip", "install", "ghostchimera[#{extra}]" or
        opoo "optional extra [#{extra}] did not install; core is unaffected"
    end
  end

  test do
    system bin/"ghostchimera", "doctor"
  end
end
