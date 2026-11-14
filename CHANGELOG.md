# Changelog

## 0.2.1 — 2026-11-14

- Add `install.py --system DESTDIR`, which prepares a `/usr` layout for distribution packages,
  and an Arch Linux (AUR) package definition in `packaging/aur/`.
- Recognize installations made by a package manager: `doctor` shows how to enable the service
  and `uninstall` points to the package manager instead of removing files.

## 0.2.0 — 2026-11-14

- Discover native, Flatpak and common alternate Steam paths, with an explicit path override.
- Support Linux desktops without GNOME, using terminal status and optional desktop notifications.
- Add XDG autostart when a user systemd manager is unavailable; preserve existing installation paths.
- Add `steam-shaders run`, `status`, `doctor`, `stop` and data-preserving `uninstall` commands.
- Validate optional configuration and ignore other users' Steam/replay processes.
- Bundle a Decky Loader plugin with progress, current-stage estimates, recent history and
  Decky completion notifications. Real Steam Deck validation is pending.
- Publish tagged releases from CI with a stable `steam-shaders.zip` link for Decky's
  "Install Plugin from URL".
- Add a small desktop archive to each release, installable on any distribution without Git;
  the desktop installer no longer copies the Decky-only module.
- `doctor` shows the startup line for Hyprland, sway and i3, which skip XDG autostart.
- The Decky ZIP ships only runtime files and the sources needed to rebuild its frontend;
  tests, the GNOME extension and the desktop installer stay out.
- While idle, the monitor refreshes its status every 10 seconds and saves its checkpoint only
  when it changes, instead of writing both files every 2 seconds.
- Share the parser, history and presentation logic across the GNOME and Decky interfaces.
- Add MIT licensing, English/Brazilian Portuguese documentation with a language switcher,
  CI and portability/lifecycle tests.
- Document Decky's restriction on submitting code mostly written by generative AI.
