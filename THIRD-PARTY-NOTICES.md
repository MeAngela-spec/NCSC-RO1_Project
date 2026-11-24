# Bundled components

The Windows installer packages Python, the dependencies in requirements.txt,
and a private LibreOffice print converter. They retain their own licenses.
NCSC branding and the supplied document template are retained as supplied;
this project does not grant third-party rights to those assets.

- Python: https://docs.python.org/3/license.html (included under licenses/python).
- PyInstaller: https://pyinstaller.org/en/stable/license.html (bootloader exception).
- Application package metadata and available license files are included in the
  frozen application's package resources / distribution metadata.
- LibreOffice: https://www.libreoffice.org/about-us/licenses/ . Its original
  license and notice files remain in the private libreoffice folder.
  Source downloads: https://www.libreoffice.org/download/download-libreoffice/
  and https://downloadarchive.documentfoundation.org/libreoffice/old/ .
- Microsoft Visual C++ runtime assemblies are taken from the build toolchain's
  redistributable directory, not its debug/compiler binaries. Applicable terms:
  https://visualstudio.microsoft.com/license-terms/ and
  https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files .
- Inno Setup builds the installer: https://jrsoftware.org/inno-setup .

The build records the converter download URL, version and SHA-256. It validates
the publisher's Windows signature before extracting the converter. The private
copy does not install/replace an existing office suite or change file associations.
