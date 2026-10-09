# Third-party notices

jav-data's Windows release bundles Python and third-party libraries. Their authors
retain their respective copyrights and licenses. The copied notices are in
`docs/third-party/`; `index.json` identifies the installed Python package versions
and their included license files. This collection also includes build-tool notices.

Qt and PySide6 are loaded as separate libraries in `_internal`. The applicable
open-source license texts are included, along with notices for Qt and Chromium
components. Compatible library replacements can be installed in the extracted
application folder; this is a folder distribution rather than a sealed installer.

Upstream information and source locations:

- [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html)
- [Qt WebEngine licensing](https://doc.qt.io/qt-6.11/qtwebengine-licensing.html)
- [Qt component notices](https://doc.qt.io/qt-6.11/licenses-used-in-qt.html)
- [PySide6 source](https://code.qt.io/cgit/pyside/pyside-setup.git/)
- [Qt source downloads](https://download.qt.io/official_releases/qt/)
- [Python source and license](https://www.python.org/downloads/source/)
- [PyInstaller license and bootloader exception](https://pyinstaller.org/en/stable/license.html)

Qt component notices were collected from the Qt 6.11 documentation. These and the
installed package notices accompany the release; they do not assign an open-source
license to jav-data's own code.
