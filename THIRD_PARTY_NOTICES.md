# Third-party notices

Steam Shaders' own code is licensed under MIT. The Decky build bundles the unmodified
runtime helpers from **@decky/api 1.1.3**, part of the
[Decky frontend libraries](https://github.com/SteamDeckHomebrew/decky-frontend-lib),
licensed under LGPL-2.1 according to its package metadata.
Its license and original TypeScript source are included in `vendor/decky-api/` in the ZIP.
The build generates this directory from the pinned dependency, without editing its sources.

React and @decky/ui are provided by Decky/Steam at runtime and are not copied into the plugin.
Build tools and their dependencies retain their respective licenses in `node_modules/`.
The ZIP includes the plugin frontend source, shared presentation model, Rollup configuration
and lockfile so the frontend can be rebuilt with a modified API dependency.

API usage and package layout follow the official Decky documentation and plugin template.
The chip icon is shared with this project's GNOME extension.
