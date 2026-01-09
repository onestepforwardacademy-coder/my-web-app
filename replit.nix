{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.python311Packages.setuptools
    pkgs.python311Packages.wheel

    # Browser stack
    pkgs.chromium
    pkgs.chromedriver

    # OCR
    pkgs.tesseract

    # Python packages from Nix
    pkgs.python311Packages.selenium
  ];

  shellHook = ''
    # Upgrade pip
    python -m pip install --upgrade pip

    # Python packages from BOTH configs
    pip install \
      selenium \
      undetected-chromedriver \
      opencv-python-headless \
      numpy \
      requests \
      pillow \
      pytesseract \
      base58 \
      solders
  '';

  env = {
    PYTHONPATH = ".";
    CHROME_BIN = "${pkgs.chromium}/bin/chromium";
    TESSDATA_PREFIX = "${pkgs.tesseract}/share/tessdata";
  };
}
