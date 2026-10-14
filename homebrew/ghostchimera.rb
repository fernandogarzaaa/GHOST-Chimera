# Homebrew formula for Ghost Chimera (tap distribution).
#
# Upstream Homebrew core admission is out of scope; ship via a tap:
#   brew tap fernandogarzaaa/ghostchimera
#   brew install ghostchimera
# See README.md for the tap setup.
#
# Maintainer release checklist:
#   1. Publish the GitHub Release (publish.yml uploads the sdist + wheel to PyPI).
#   2. Point url at the PyPI sdist and update sha256
#      (`curl -sL <url> | shasum -a 256`; PyPI also lists it under "Download files").
#   3. `brew audit --new ghostchimera` and `brew test ghostchimera` before tap push.
class Ghostchimera < Formula
  include Language::Python::Virtualenv

  desc "Background AI infrastructure: ambient intelligence runtime for AI agents"
  homepage "https://github.com/fernandogarzaaa/GHOST-Chimera"
  url "https://files.pythonhosted.org/packages/ee/8a/c787c9526677b0a3ed10a31fc0b4e241c894050448e3b2fbdce15ea79dc5/ghostchimera-0.4.0b1.tar.gz"
  sha256 "8f4151ee4cf521fcce73e9a6ffc988fa8f9ae63199b023cb0b5e96035be4a738"
  license "MIT"
  head "https://github.com/fernandogarzaaa/GHOST-Chimera.git", branch: "main"

  depends_on "python@3.12"

  def install
    # Installs the released sdist (v0.4.0-beta.1 = PyPI 0.4.0b1), not whatever
    # is newest on PyPI. There are no `resource` blocks yet, so pip resolves the
    # small core runtime dependencies (certifi, croniter, cryptography,
    # jsonschema, websockets) from PyPI during install.
    venv = virtualenv_create(libexec, "python3.12", without_pip: false)
    system venv.root/"bin/python", "-m", "pip", "install", "--no-cache-dir", buildpath
    %w[ghostchimera ghost chimera-pilot].each do |cmd|
      bin.install_symlink libexec/"bin"/cmd
    end
  end

  def caveats
    <<~EOS
      Only the core runtime is installed. Optional backends (desktop, mcp,
      gateway, local, quantum, minimind, voice) are opt-in; pin the same
      version so pip does not replace the installed build, e.g.:
        #{opt_libexec}/bin/python -m pip install "ghostchimera[mcp]==#{version}"
    EOS
  end

  test do
    system bin/"ghostchimera", "doctor"
  end
end
