# UI 36: install optional NumPy acceleration

## Use in Maya

1. Replace the complete installed tool folder with this package's files.
2. Run its `layer_skin_ui_refresh.py` with `run_name="__main__"`; confirm **UI 36**.
3. Open **Utilities → Performance**. The status uses the active command's helper.
4. If NumPy is unavailable, click **Install NumPy** and keep Maya open while the
   installer checks Python, installs and verifies the wheel.
5. The status changes to **NumPy 1.26.4 ready** after a successful current-session
   import. **Recheck NumPy** can also detect a separate manual installation.

You can keep your existing folder name, including `Layer_Skin_0_4_1_UI_34`, when
replacing its contents. Run the refresh with `__main__` to actually replace the
window; the earlier `run_name="layer_skin_check"` diagnostic only reads it.

For the original installation location, after replacing that folder's files:

```python
import runpy
runpy.run_path(
    r"D:/dev/MayaZone/Layer_Skin_0_4_1_UI_34/layer_skin_ui_refresh.py",
    run_name="__main__"
)
```

Adjust the folder path when using a different location. The plug-in remains
0.4.1 and keeps registered native Undo objects. UI 35's Select vertices fix is
included; no viewport or skin-weight math changes are introduced here.

## Installation behavior

Installation is optional and starts only on an explicit button click. Normal
Layer Skin operations retain the standard-library comparison if NumPy cannot
load. The installer uses Maya's `mayapy` executable, rather than launching
`maya.exe` with Python arguments. It checks Python major/minor, platform, bitness
and pip availability before invoking pip. It uses QProcess without a shell.

The package is pinned to **NumPy 1.26.4**, whose supported Python versions are
3.9–3.12. An existing working NumPy version is reused and is not upgraded or
unloaded. Automatic installation is disabled on other Python versions; a
compatible manually installed backend can still be detected with Recheck.
The pin retains the NumPy 1.x ABI rather than introducing NumPy 2's ABI change
into a Maya installation that may contain extensions built against NumPy 1.x.

Pip uses `--only-binary=:all:`, `--no-deps` and a fresh `--target` staging folder
under Maya's user app directory. It does not install into Maya's application
directory, replace an existing NumPy directory or upgrade unrelated packages.
The configured pip index/proxy/certificate settings are honored. Installation
needs network access and a compatible binary wheel; it does not compile NumPy.

A second child process imports that exact staged NumPy and checks a float64
comparison. Only then is the folder published with an atomic `active.json`
pointer. Python ABI/platform folders are separate. On later launches, the native
performance helper locates the active folder through Maya's user app directory
and appends it to the search path without reordering the existing paths.

The earlier failed-import cache is cleared by Recheck and after installation.
Already loaded NumPy modules are never removed or reloaded. A binary/DLL import
failure keeps the standard comparison available and records its error. If the
child verification succeeds but the current Maya process cannot import it, the
panel displays a restart message and the import details instead of repeatedly
reinstalling the package. A restart may still require resolving a conflicting
Python search path or DLL, as explained by the import error.

Cancel, timeout, failed verification and closing/reloading the window stop the
owned child process and discard its inactive staging folder when removable.
No failed staging folder is published. Previous successful package directories
are retained, so loaded binary files are not deleted under a running Maya.
Missing pip, missing mayapy and network or wheel errors appear in the panel;
existing skin/layer data and native Undo are unaffected by installation.

## Verification

The automated suite passes **936 checks**, including 29 new dependency/backend
and actual-Qt installer checks. Coverage includes cached failure/retry, binary
import errors, matching mayapy, ABI and pip checks, separate argument handling,
atomic activation and rollback, path validation, success, errors, Cancel,
timeout, shutdown, restart-required status, unsupported Python, manual Recheck
and selecting the active command helper in the real Utilities page.

A separate end-to-end run started CPython without site-packages, with NumPy
initially unavailable. Actual Qt/QProcess and pip installed a local Linux wheel,
verified and activated it, then imported NumPy 1.26.4 in the same running process.
The fast comparison passed its tolerance check, and a Qt heartbeat continued
through installation. No Maya runtime was available: this used a matching
CPython executable as a mayapy stand-in. Windows/Maya DLL loading, corporate
network policy and native Maya integration still need testing there. Details
are in `NUMPY_INSTALL_INTEGRATION.json` and `VALIDATION.md`.

The Utilities layout was inspected at 1280×940; its import actions stay visible
while the added Performance group scrolls with the existing options.

## References

- [Autodesk: mayapy and pip package management](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-Scripting/files/GUID-72A245EC-CDB4-46AB-BEE0-4BBBF9791627.htm).
- [NumPy 1.26.4 supported Python versions](https://numpy.org/doc/2.3/release/1.26.4-notes.html).
- [NumPy 2.0 ABI changes](https://numpy.org/devdocs/release/2.0.0-notes.html).
- [pip install options](https://pip.pypa.io/en/stable/cli/pip_install/).
