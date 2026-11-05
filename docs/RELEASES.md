# Releases: how the three downloads are made

Every GitHub Release has exactly three files, built by `.github/workflows/release.yml` from one commit:

| File | What it is | Built on | Job |
|---|---|---|---|
| `iPreent-vX.Y.Z.apk` | Android app, signed with the release key | `ubuntu-24.04` | `android` |
| `iPreent-vX.Y.Z-portable.exe` | Windows app, one file, no install, no Python | `windows-latest` | `windows` |
| `ipreent-cli-vX.Y.Z.zip` | Command line (source + `INSTALL.txt`), installed with `pip install .` | `ubuntu-24.04` | `cli` |

The `release` job runs after all three, downloads their artifacts and publishes them with
`softprops/action-gh-release`. Its notes are the `## vX.Y.Z` section of `CHANGELOG.md` (an awk script takes
the lines between that heading and the next `## `; a missing section gives "Built from <sha>.").
`## Unreleased` at the top of the changelog is never published; rename it to the version when cutting.

## Cutting a release
1. Bump the version in **all three** places:
   - `pyproject.toml` → `version`
   - `ipreent/__init__.py` → `__version__` (shown by `ipreent`, the HTTP API and the exe)
   - `android/app/build.gradle.kts` → `versionName`, and `versionCode` **+1** (Android refuses an update with the
     same or a lower versionCode; Obtainium also relies on it).
2. Turn `## Unreleased` in `CHANGELOG.md` into `## vX.Y.Z` (exactly the tag, with the `v`).
3. Commit and push to `main`.
4. Start the workflow:
   - From the owner's PC: `git tag vX.Y.Z && git push origin vX.Y.Z`.
   - From a Claude cloud session (the git proxy refuses tag pushes with HTTP 403): GitHub tool
     `actions_run_trigger` → `run_workflow`, `workflow_id: release.yml`, `ref: main`,
     `inputs: {"version": "vX.Y.Z"}`. The release step creates the tag on the commit it built.
     Or Actions tab → Release → Run workflow.
5. Watch jobs `android`, `windows`, `cli`, then `release` (`windows` is slowest, about 6 min). Check the release
   page lists the three files.

Manual runs have a `publish` input: `false` only builds and tests (use it to try workflow changes). Re-running a
version that already exists replaces its files but leaves its tag. **Never move or delete a published tag.**

## Android APK
- Code: `android/` (Kotlin + Jetpack Compose, Material 3). minSdk 26 (Android 8), target/compile 35.
- CI: `./gradlew --no-daemon testDebugUnitTest assembleRelease` (R8 minify on), then
  `apksigner verify --print-certs` must show the release certificate SHA-256 in `RELEASE_CERT_SHA256`.
- Signing: secrets `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (`ipreent`),
  `ANDROID_KEY_PASSWORD`. The workflow decodes the keystore to `$RUNNER_TEMP` and `build.gradle.kts` reads it
  through `IPREENT_KEYSTORE*` / `IPREENT_KEY_*`. Without the secret a publishing run **fails** (a build-only run
  warns and signs with a throwaway debug key, which can't update over a real release).
- Key: `CN=iPreent, O=MT, C=CL`, RSA 4096, valid until 2054, SHA-256
  `BC:EE:AA:9A:F6:AC:AE:F4:F8:61:15:75:C1:76:2F:BA:B4:17:97:62:C8:8F:09:2E:4F:28:D3:52:BA:A4:61:E1`.
  The owner keeps the keystore and password. Never commit them.
- History: v0.4.0's APK was debug-signed; v0.4.1 is the first with the release key, so phones on v0.4.0 uninstall
  once. From v0.4.1 on, every APK installs over the previous one.
- Users install it from the release page or with **Obtainium** (README badge →
  `https://apps.obtainium.imranr.dev/redirect?r=obtainium://add/https://github.com/matias-saavedra-g/iPreent`).
  Obtainium reads the GitHub Releases of the repo (it needs the repo to be **public**, or a GitHub token in its
  settings), takes the `.apk` asset and compares the tag with the installed `versionName`.
- Local build in a cloud session: no SDK is installed; see CLAUDE.md (cmdline-tools in the scratchpad,
  `android/local.properties`, Maven mirror init script for HTTP 429).

## Portable Windows exe
- Code: `ipreent/desktop/` (PySide6) on top of the shared `ipreent/` package.
- Build: `pip install -e ".[desktop]" pyinstaller` then `python tools/build_windows.py` → `dist/iPreent.exe`
  (PyInstaller `--onefile --windowed`; `--debug` builds a console version that shows tracebacks). It renders the
  `.ico` from `assets/brand/*.svg`, bundles `models.json` and `ipreent/desktop/icons`, collects `bleak` + `winrt`,
  and leaves out unused Qt modules. **Only builds on Windows** (WinRT Bluetooth, `winreg`), hence the Windows runner.
- Not code-signed: SmartScreen may warn on first start ("More info → Run anyway").
- No installer and no updater: the user downloads the new exe and replaces the old one. Settings live in the
  registry (`HKCU\Software\iPreent\iPreent`), so they carry over.
- Tests for its Python code run in the `cli` job on Linux (two Windows-only tests are deselected there).
  The window itself can be driven offscreen on Linux with `winreg`/`ctypes.windll` stubbed (see JOURNAL).

## Command-line zip
- Contents: `ipreent/` (the package, including `desktop/`), `pyproject.toml`, `README.md`, `PROTOCOL.md` and
  `INSTALL.txt` (from `tools/cli-install.txt`). `__pycache__` is left out.
- CI runs `pytest` first (deselecting `test_print_detects_image` and `test_emoji_text_uses_emoji_font`, which need
  Windows or an emoji font).
- Install: Python 3.10+ (pyproject says `>=3.9`), then `pip install .` in the unzipped folder; gives the `ipreent`
  command (and `ipreent-desktop` if `.[desktop]` is installed). Dependencies: bleak, Pillow, pyserial, pypdfium2.
- Update: unzip the new version and `pip install .` again. Settings in the config dir (see ARCHITECTURE.md) stay.
- Works on Windows, Linux (BlueZ) and macOS; only the Windows app is Windows-only.

## Workflow maintenance
- Ubuntu is pinned to `ubuntu-24.04` on purpose. Actions are on their Node 24 majors (checkout v7, setup-python
  v7, setup-java v6, setup-gradle v6, upload-artifact v7, download-artifact v8, action-gh-release v3). When a
  deprecation notice shows up, bump the major and read its breaking changes first.
- The workflow only runs on tag pushes and manual dispatch (both need write access), so forks and pull requests
  never see the signing secrets. Keep it that way: don't add `pull_request_target`, and keep `${{ }}` expressions
  out of `run:` scripts (pass them through `env:`).
- Gradle 8.11.1 / AGP 8.7.3 / Kotlin 2.0.21. Moving to Gradle 9 needs a newer AGP and Kotlin: do it in its own change.
