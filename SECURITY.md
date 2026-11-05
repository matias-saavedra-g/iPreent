# Security

## Reporting a problem
Please report security issues privately through GitHub: **Security** tab → **Report a vulnerability**.
Don't open a public issue for them. Ordinary bugs go in Issues.

## What iPreent does and doesn't do
- **No network service by default.** The apps talk to the printer over Bluetooth only. Nothing is sent to the
  internet: no accounts, no analytics, no vendor server.
- **Windows HTTP API** (off by default, turned on from the tray menu):
  - Local mode listens on `127.0.0.1:8787` with no token. It refuses requests from web pages (any `Origin` header,
    or `Sec-Fetch-Site: cross-site/same-site`) and any `Host` that isn't localhost, so a website you visit can't
    make the printer print or read the queue (including through DNS rebinding). Scripts, curl and other programs
    on the same PC can use it, as intended.
  - LAN mode listens on all interfaces and every request needs the bearer token (144 random bits, compared in
    constant time). Traffic is plain HTTP, so use it only on a network you trust.
- **"Print from any app" printer** (Windows, optional, needs one admin prompt): Windows' own *Microsoft Print to
  PDF* driver writes to `C:\ProgramData\iPreent\spool`, which every local user can write to. Anyone signed in to the
  PC can therefore send something to the printer while the app runs. Remove it from the tray menu if that matters.
- **Android**: Bluetooth permissions only (location only on Android 11 and older, as the system requires for BLE
  scans). No internet permission. The share target and print service only print what they are given.
- **Release APKs** are signed with the iPreent key (certificate SHA-256
  `BC:EE:AA:9A:F6:AC:AE:F4:F8:61:15:75:C1:76:2F:BA:B4:17:97:62:C8:8F:09:2E:4F:28:D3:52:BA:A4:61:E1`).
  Check a download with `apksigner verify --print-certs iPreent-vX.Y.Z.apk`. The Windows exe is not code-signed.

## Repository audit (2026-11-05)
Done before making the repository public. Result: nothing secret in the code or in the history.
- All commits and every file ever committed were searched for private keys, keystores (`.jks`, `.p12`, `.keystore`),
  passwords, API keys and tokens (GitHub, AWS, Google, Slack, Anthropic patterns), `.env` and `local.properties`:
  none found. The signing key lives only in the repository secrets and with the owner.
- One file that was committed and later removed, `android/.kotlin/errors/*.log`, only holds a compiler message with
  a build container's proxy settings (no credentials).
- The release workflow runs only on tag pushes and manual runs (both need write access). It has no
  `pull_request`/`pull_request_target` trigger, so forks can't reach the secrets, and it doesn't splice `${{ }}`
  expressions into shell scripts.
- Fixed during the audit: the local HTTP API used to accept requests from web pages (see above).
- Personal details that are public on purpose: commit author names/emails, the test printer's Bluetooth address
  in notes, the Windows user folder name in `MANUAL_DEBUGGING.md` logs, and the business name used in examples.
- `models.json` holds printer parameters (model numbers, dpi, speeds, MTU) read from the vendor's Android app to
  make these printers work without it (interoperability). No vendor code, images or text are included.
