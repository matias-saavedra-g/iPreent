# iPreent: notes for Claude

Offline driver for cheap BLE thermal "cat" printers: Python CLI + Windows app (`ipreent/`, `ipreent/desktop/`) and an
Android app (`android/`, Kotlin + Compose). README.md has usage and layout; PROTOCOL.md has the printer protocol.

## Conventions
- **JOURNAL.md** is the project log: add findings, decisions and open questions under today's date (newest at the
  bottom). Old entries say `freeprint`; that's history.
- The Android app is a port of the Python code: `protocol.py` ↔ `Protocol.kt`, `imaging.py` ↔ `Imaging.kt`,
  `receipt.py` ↔ `Receipt.kt`. Change both and keep the shared test cases in step (`tests/` ↔ `android/app/src/test`).
- Tests: `pytest -q`. On Linux, `test_emoji_text_uses_emoji_font` (no emoji font) and `test_print_detects_image`
  (needs `winreg`) fail; that's expected. Android: `cd android && sh ./gradlew testDebugUnitTest assembleRelease`.
- Cloud sessions have no Android SDK: install cmdline-tools into the scratchpad and point `android/local.properties`
  (git-ignored) at it. If Maven Central answers 429, pass a Gradle init script (`-I`) that adds
  `https://maven-central.storage-download.googleapis.com/maven2/` in `beforeSettings`. Don't commit that.

## Releases
`.github/workflows/release.yml` builds three files and publishes them as a GitHub Release:
`iPreent-vX.Y.Z.apk` (Ubuntu, after the Android unit tests), `iPreent-vX.Y.Z-portable.exe` (Windows runner +
PyInstaller; it can't be built from Linux) and `ipreent-cli-vX.Y.Z.zip` (source + `tools/cli-install.txt`, after
pytest). The release notes are the `## vX.Y.Z` section of CHANGELOG.md.

To cut a release:
1. Bump the version in **all** of: `pyproject.toml`, `ipreent/__init__.py`, and `android/app/build.gradle.kts`
   (`versionName`, and `versionCode` + 1: Android refuses to install an update without a higher versionCode).
2. Add a `## vX.Y.Z` section to CHANGELOG.md. The heading has to match the tag exactly, or the notes come out empty.
3. Commit and push to `main`.
4. Start the workflow, either way:
   - **Tag push** (from the owner's PC): `git tag vX.Y.Z && git push origin vX.Y.Z`.
   - **Manual run**: in a Claude cloud session, **tag pushes are refused by the git proxy (HTTP 403)**, so use the
     GitHub tool `actions_run_trigger` → `run_workflow`, `workflow_id: release.yml`, `ref: main`,
     `inputs: {"version": "vX.Y.Z"}`. (Or Actions tab → Release → Run workflow.) The release step then creates the
     tag on the commit it built.
5. Watch the run (jobs `android`, `windows`, `cli`, then `release`) and check the release has the three files.
   The `windows` job is the slowest (~6 min).

Notes:
- `publish: false` on a manual run only builds and tests. Use it to check workflow changes without touching a release.
- Re-running for a version that already exists replaces that release's files (`overwrite_files` defaults to true)
  but leaves its tag where it was. Never move or delete a published tag.
- Runners: Ubuntu is pinned to `ubuntu-24.04` on purpose; action majors are the Node 24 ones (checkout v7,
  setup-python v7, setup-java v6, setup-gradle v6, upload-artifact v7, download-artifact v8, action-gh-release v3).
  When a deprecation notice appears, bump the major and check its breaking changes before merging.

### APK signing
- Release APKs are signed with the key in the repository secrets `ANDROID_KEYSTORE_BASE64`,
  `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (`ipreent`) and `ANDROID_KEY_PASSWORD`. The workflow decodes
  the keystore and `android/app/build.gradle.kts` reads it from the `IPREENT_KEYSTORE*` / `IPREENT_KEY_*` env vars.
- Key: `CN=iPreent, O=MT, C=CL`, RSA 4096, valid until 2054. Certificate SHA-256
  `BC:EE:AA:9A:F6:AC:AE:F4:F8:61:15:75:C1:76:2F:BA:B4:17:97:62:C8:8F:09:2E:4F:28:D3:52:BA:A4:61:E1`.
  Check a built APK with `apksigner verify --print-certs`.
- The owner keeps the keystore and its password. Never commit them. If the secrets are missing, the build falls back
  to the runner's throwaway debug key: the APK installs fine but won't update over a release signed with the real
  key, so treat that as a failed release. v0.4.0's first APK was debug-signed.
