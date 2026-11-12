# Changelog

## 0.2.0 — unreleased

- Discover native, Flatpak and common alternate Steam paths, with an explicit path override.
- Support Linux desktops without GNOME, using terminal status and optional desktop notifications.
- Add XDG autostart when a user systemd manager is unavailable; preserve existing installation paths.
- Add `steam-shaders run`, `status`, `doctor`, `stop` and data-preserving `uninstall` commands.
- Validate optional configuration and ignore other users' Steam/replay processes.
- Bundle a manually installable Decky Loader plugin with progress, current-stage estimates,
  recent history and Decky completion notifications. Real Steam Deck validation is pending.
- Share the parser, history and presentation logic across the GNOME and Decky interfaces.
- Add MIT licensing, English/Brazilian Portuguese documentation, CI and portability/lifecycle tests.
- Document Decky's restriction on submitting code mostly written by generative AI.
