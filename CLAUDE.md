# iPreent: notes for Claude

Offline driver for cheap BLE thermal "cat" printers: Python CLI + Windows app (`ipreent/`, `ipreent/desktop/`) and an
Android app (`android/`, Kotlin + Compose). README.md has usage; PROTOCOL.md has the printer protocol.

**Start here instead of re-reading the code:** `docs/ARCHITECTURE.md` (module map, Python ↔ Kotlin twins, how each
app prints, where each app stores state) and `docs/RELEASES.md` (how the APK, portable exe and CLI zip are built,
versioned, signed, installed and updated). `SECURITY.md` has the threat model and the pre-public audit. When a
change makes any of these wrong, fix the doc in the same commit.

## Conventions
- **Languages** (English + Spanish): Android strings are in `res/values*/strings.xml`; the CLI and Windows app wrap
  every text people read in `tr("English text {0}", value)` (`ipreent/i18n.py`) and translate it in
  `ipreent/locales/es.json`. Anything untranslated must stay working in English. New texts: add the Spanish too,
  keep `%`/`{0}` placeholders the same (tests check). HTTP API messages stay English. `IPREENT_LANG=es` tries it.
- **JOURNAL.md** is the project log: add findings, decisions and open questions under today's date (newest at the
  bottom). Old entries say `freeprint`; that's history.
- The Android app is a port of the Python code: `protocol.py` ↔ `Protocol.kt`, `imaging.py` ↔ `Imaging.kt`,
  `receipt.py` ↔ `Receipt.kt`, `features.py` ↔ `Features.kt`, `templates.py` ↔ `Templates.kt` (the template SVGs and
  fonts are copied into `android/app/src/main/assets`; a test checks they match). Change both and keep the shared test cases in step
  (`tests/` ↔ `android/app/src/test`). Print-time estimates live in `protocol.py` / `Protocol.kt` too.
- Python tests never touch the real config dir (`tests/conftest.py` points it at a temp dir); keep it that way, since
  printing now writes `timing.json`, `usage.json` and the `print.lock` / `busy.json` pair there.
- Tests: `pytest -q`. On Linux, `test_emoji_text_uses_emoji_font` (no emoji font) and `test_print_detects_image`
  (needs `winreg`) fail; that's expected. Android: `cd android && sh ./gradlew testDebugUnitTest assembleRelease`.
- Cloud sessions have no Android SDK: install cmdline-tools into the scratchpad and point `android/local.properties`
  (git-ignored) at it. If Maven Central answers 429, pass a Gradle init script (`-I`) that adds
  `https://maven-central.storage-download.googleapis.com/maven2/` in `beforeSettings`. Don't commit that.
- To look at Compose screens without a phone: a temporary Robolectric 4.14.1 test with `@GraphicsMode(NATIVE)`
  that draws the root views to PNGs (make the composables `internal` for the run). Revert it all afterwards; never
  commit the test or the dependency. Screens with indeterminate spinners render slowly (minutes).

## Releases
Full procedure and how each download works: `docs/RELEASES.md`. The things that bite:
- Bump the version in `pyproject.toml`, `ipreent/__init__.py` and `android/app/build.gradle.kts` (`versionName`
  **and** `versionCode` + 1), and rename `## Unreleased` in CHANGELOG.md to `## vX.Y.Z` (must match the tag).
- Cloud sessions can't push tags (git proxy 403): start `release.yml` with `actions_run_trigger` → `run_workflow`,
  `ref: main`, `inputs: {"version": "vX.Y.Z"}`. `publish: false` only builds and tests.
- Never move or delete a published tag. Never commit the keystore or its password (they're repository secrets and
  the owner's). A debug-signed APK is a failed release; the workflow refuses to publish one.
- Obtainium users update from the GitHub Releases, so every release needs the signed `.apk` asset and a higher
  versionCode.
