# Changelog

[简体中文](CHANGELOG.zh-CN.md)

Sections: `Added` / `Changed` / `Fixed` / `Removed`. Dates are when the work was
finished on the development machine.

## 1.1.1 — 2026-09-12

### Added
- **A Windows installer.** One `recollect-1.1.1-setup.exe` you double-click. It
  installs per-user under `%LOCALAPPDATA%\Programs`, so it never asks for
  administrator rights, and it registers in *Settings -> Apps* like any other
  program. The wizard offers the install location, desktop and start-menu
  shortcuts, and start-with-Windows
- The installer and uninstaller are drawn in the same *paper and seal* language
  as the app itself — pure ctypes against Win32, GDI+ for antialiased shapes,
  GDI for ClearType text. No Inno Setup and no NSIS, so building one needs
  nothing that isn't already here
- `--silent` for unattended setup, with `--dir`, `--no-desktop`, `--no-menu`,
  `--autostart` and `--launch`. Exits 0, or 1 with the reason on stderr. Run
  from a terminal it prints there, double-clicked it stays quiet
- Uninstall lives inside the app (`拾遗.exe --uninstall`) rather than in a
  separate uninstaller.exe that a disk cleanup can delete, leaving a program
  that cannot be removed. It asks once whether the index should go too; say no
  and a later reinstall picks up where you left off

### Changed
- The desktop UI layer refuses bold below 12pt. Microsoft YaHei ships no
  Semibold, so GDI fakes one by thickening strokes — which at small sizes turns
  dense glyphs like 删, 露 and 麟 into a solid black block. Below that size
  hierarchy comes from size and colour instead. The rule lives in the font
  cache, so no call site has to remember it
- The repository root holds only what belongs there. The five Windows batch
  files that used to sit beside the README are down to one, `tools\打包.bat`.
  The installer creates the shortcuts and the tray menu rescans, so the scripts
  that did those by hand had nothing left to do
- Release assets use ASCII filenames. GitHub strips CJK characters from asset
  names, so a Chinese one would arrive as `-1.1.1-.exe`. The installed program
  is still called 拾遗; only the outer wrapper's filename changed
- Android `versionCode` 4 / `versionName` 1.1.1, to keep one version number
  across the product. The app itself is unchanged from 1.0.1

## 1.0.1 — 2026-09-11

### Added
- Redesigned interface around a design language called *paper and seal*:
  depth comes from light, not borders; the vermillion accent is reserved for
  exactly three things — current location, primary action, search highlight
- A motion system following Material 3's scale: 120 ms for micro-interactions,
  200 ms for components, 300 ms for containers, 380 ms for screen-level
  transitions; decelerating curves for entrances, accelerating for exits.
  Results stagger in, the detail panel slides from the right, yearbook bars
  grow from the baseline, skeletons replace spinners. All of it switches off
  under `prefers-reduced-motion`
- Deep links: `?q=<term>` opens with a query, `#tidy` opens on that screen,
  so a result set or a view can be bookmarked and shared
- Recent searches replaced the hardcoded example terms — stored in the
  browser only, never uploaded, never indexed
- **Android app** (`android/`): Kotlin + Compose + Material 3, same design
  language, same text-extraction approach

### Changed
- The first result is selected automatically — the right half of the window is
  no longer empty, and it saves a click
- Kind filters are ordered by importance (documents / slides / PDF / sheets …)
  rather than by count, which used to let "other · 103,630" own the first slot
- An empty query lists *work* only, instead of putting `.lnk` and `.gitignore`
  on the first screen
- Sidebar statistics moved up under the navigation as an aligned key-value block
- Android release builds now succeed without the signing keystore (producing an
  unsigned APK) — otherwise the first thing a fresh clone does is fail to build

## 1.0.0 — 2026-09-11

From a working script into an actual piece of software.

### Added
- **Application shell**: single instance (clicking the icon again raises the
  window you already have, it never starts a second copy), tray residency,
  closing the window doesn't quit, clean shutdown
- **System tray**: pure ctypes against Win32, no pystray, no Pillow.
  Left-click opens; right-click offers scan now / open index folder / view
  logs / quit; a balloon reports what changed after a scan
- **Application window**: Edge or Chrome in `--app` mode with an isolated
  user-data directory, fully separate from your everyday browser. Falls back
  to the default browser when neither is installed
- **Automatic scanning**: once at startup, then on an interval, incrementally
- **Settings screen**: scan roots, extra exclusions, body-text indexing and its
  limit, scan interval, appearance (system / light / dark), start with Windows,
  create shortcuts
- **About screen**: version and environment, index check / compact / rebuild /
  clear, keyboard reference, logs, quit and uninstall
- **First-run guide**: states plainly what it does and what it won't, then asks
  you to confirm the scan roots
- **Logging** to `~/.shiyi/shiyi.log`, rotating, 3 files kept; uncaught
  exceptions are recorded too — which is how the packaging bug below was found
- **Search**: pagination, sort by relevance / time / size, CSV export
- **Windows integration**: autostart via the HKCU Run key, desktop and start
  menu shortcuts, uninstall
- **Icon**: the 拾 glyph rendered through GDI into a bitmap, then an ICO
  container written by hand — seven sizes, no Pillow
- **Packaging**: `pyproject.toml` (a `shiyi` command after `pip install -e .`),
  a PyInstaller build script, MIT license

### Changed
- A busy port rolls forward to the next free one, so double-clicking never
  produces a traceback
- The index health check became opt-in: `PRAGMA quick_check` takes seconds on a
  400 MB database and has no business running every time About is opened
- Appearance and autostart apply immediately; leaving Settings no longer traps
  you behind a `confirm()` — an unsaved-changes dot on the sidebar instead
- A malformed config is clamped into range rather than preventing startup

### Fixed
- Skip messenger private databases (`db_storage`, `.db-wal`, `.material`) —
  one pass removed 3,774 files that were never the user's to begin with

## 0.1.0 — 2026-09-10

The first version that worked.

### Added
- Full scan and incremental indexing: ~90 s for 150,000 files, ~9 s incremental
- Chinese full-text search on SQLite FTS5 with the trigram tokenizer: ~1 ms for
  three characters or more; one or two characters fall back to scanning body text
- Text extraction: docx / pptx / xlsx parsed straight out of OOXML; PDF decoded
  from scratch — FlateDecode, object streams, `/ToUnicode` CMaps, then
  reading-order reconstruction from glyph coordinates. No pypdf
- Project detection, version clustering, content-fingerprint deduplication
- Yearbook: files translated into "what you made this year", exportable as a
  single self-contained HTML page
- Web interface and command line

### Fixed
- Submit scan jobs in bounded chunks — `Executor.map` over 150,000 jobs queues
  them all at once, and extraction outruns the database writer until memory
  is gone
- Skip OneDrive cloud placeholders instead of triggering a download for each
- The per-directory text budget must not apply to docx / pptx / pdf — those are
  zip containers where size says nothing about word count
- Drain the request body before replying 403, or HTTP/1.1 keep-alive carries
  the leftover bytes into the next request
