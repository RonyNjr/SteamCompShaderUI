# Steam Shaders on Decky Loader

**English** · [Português do Brasil](decky.pt-BR.md)

The plugin shows progress in Decky's quick access menu: game, percentage, stage,
current-stage estimate and recent history. A Decky notification confirms completion.
The plugin's interface is in Brazilian Portuguese in this version.

**Status:** experimental. The frontend builds, the backend is tested against a simulated Decky
API, and the API and Python modules it uses were checked against Decky Loader 3.3.1.
It has not yet been validated on a real Steam Deck. The plugin is not in the Decky store.

## Install from URL

This works once a release has been published on GitHub.

1. In Decky, open **Settings › General** and enable **Developer mode**.
2. In **Settings › Developer**, find **Install Plugin from URL**.
3. Enter the address below and select **Install**:

   ```text
   https://github.com/RonyNjr/SteamCompShaderUI/releases/latest/download/steam-shaders.zip
   ```

4. Open **Steam Shaders** from the plugin menu. Detection and monitoring start automatically.

To update, install again from the same address; it always points to the latest release.

## Install from a ZIP file

1. Download `steam-shaders.zip` from the [releases page](https://github.com/RonyNjr/SteamCompShaderUI/releases)
   or build the package locally as described in [Build](#build).
2. With Developer mode enabled, use **Install Plugin from ZIP File** and select the file.

The Steam Deck does not need the desktop service, GNOME, Node.js or Python packages.
The monitor is bundled in the ZIP and runs in the Python backend that Decky already provides.
The plugin does not use the `_root` flag, start external commands or download data.
It does not change Steam files or cancel compilations.

Disabling or removing the plugin stops its monitor. The code does not delete history;
Decky remains responsible for the plugin's directories.
The desktop installation and the plugin keep separate histories. If you use both, disable
notifications in one of them to avoid duplicate alerts.

## Build

From the repository, with Python 3.9+, Node.js 22+ and pnpm **9** installed:

```sh
pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run build
pnpm test
pnpm run package
```

Without pnpm installed, run each command with `npx --yes pnpm@9.15.9` in place of `pnpm`,
without installing tools globally. These tools are only needed for development.

The package is written to `dist/steam-shaders-0.2.0.zip`:

```text
steam-shaders/
  plugin.json
  package.json
  main.py
  dist/index.js
  py_modules/steam_shaders/monitor.py
  py_modules/steam_shaders/support.py
  py_modules/steam_shaders/decky.py
  README.md
  LICENSE
```

The build copies the `steam_shaders/` package into the temporary `build/decky/` area.
The frontend uses `integrations/shared/model.js` to present the same information as GNOME.
There is no second implementation of the log parser.

Runtime files are placed in `build/decky/dist/`, `build/decky/py_modules/` and
`build/decky/vendor/`. The packager moves them to the paths Decky expects inside the ZIP.
The ZIP also includes the sources and licenses needed to rebuild the frontend; tests, the GNOME
extension and the desktop installer are left out.

## Configuration and diagnostics

The backend stores state, log cursor and history in `DECKY_PLUGIN_RUNTIME_DIR`. Optional
configuration lives in `DECKY_PLUGIN_SETTINGS_DIR/config.json`; Decky defines the exact
directories, so the plugin does not assume the user is called `deck`.

```json
{
  "steam_dir": "/absolute/path/to/Steam",
  "notifications": false
}
```

Omit `steam_dir` for automatic detection. Omit `notifications` to receive alerts.
Reload the plugin after editing the configuration. Backend failures appear in the plugin log
kept by Decky. A missing `shader_log.txt` can mean pre-caching has not produced activity yet;
also check Steam's settings.

## On-device validation

Before treating this version as stable, we need to record:

- SteamOS and Decky versions used, on both Stable and Beta channels.
- Game and progress appearing during a real compilation, navigating with the controller.
- A notification after confirmed completion, and no success alert for interruptions.
- Reloading and disabling the plugin stopping the monitor, with no leftover processes.
- Behavior when suspending/resuming the Steam Deck, launching a game and closing Steam.

Automated checks do not replace these tests. A real screenshot of the Decky interface should
also be captured before preparing a store listing.

## Current store restriction

Checked on **2026-11-12**: the [official form for new plugins](https://github.com/SteamDeckHomebrew/decky-plugin-database/blob/main/.github/PULL_REQUEST_TEMPLATE/plugin_addition.md)
requires declaring that most of the submitted code was not written by generative AI.
This project was developed with AI assistance and cannot honestly make that declaration
in its current state. Distribution therefore happens through GitHub releases, installed from
URL or ZIP; the project is not ready for an eligible store submission.

The same form asks for author validation on SteamOS Stable and Beta and anticipates
third-party testing. The [store repository](https://github.com/SteamDeckHomebrew/decky-plugin-database)
explains submission by pull request. If the policy changes or maintainers clarify a path that
applies to this project, eligibility should be reassessed without omitting how the code was produced.

Implementation references: [official template](https://github.com/SteamDeckHomebrew/decky-plugin-template),
[Decky Python API and paths](https://github.com/SteamDeckHomebrew/decky-loader/blob/main/backend/decky_loader/plugin/imports/decky.py)
and [frontend API](https://github.com/SteamDeckHomebrew/decky-frontend-lib).
