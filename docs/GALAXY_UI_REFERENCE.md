# Galaxy web UI reference

## Source authority inspected

- Repository: `Zoomzoomcarboi/StarPilot` (local checkout remote)
- Revision: `c1fd07db6d4ce5db51b3ec896dac7db43454e365` (2026-08-16)
- Web root: `starpilot/system/the_galaxy/`
- Shell: `the_galaxy.py`, `templates/index.html`
- Router/navigation: `assets/components/router.js`, `sidebar.js`, `sidebar.css`
- Tokens/type/layout: `assets/components/main.css`
- Cards/grids: `assets/components/home/home.js`, `home/home.css`
- Controls/status: `assets/components/settings.css`, `tools/toggles.css`
- Modals: `assets/components/modal.js`, `modal.css`
- Fonts: `assets/vendor/fonts/fonts.css`

This is the actual Flask + Arrow.js Galaxy browser application. It is distinct from
Raylib/Aether code under `selfdrive/ui/` and `starpilot/ui/`; those files were not used
as the browser implementation reference.

## Faithfully ported styling contract

Gate 1 keeps RAVE-specific markup, routes, state, and vanilla JavaScript, while
faithfully porting the relevant MIT-licensed Galaxy declarations onto the equivalent
RAVE shell selectors. This includes:

- `#06060f` main, `#0a0a16` sidebar, `#0e0e1a` secondary, `#121224` cards;
- `#1e1e3e` borders and `#161630` inputs;
- `#8b6cc5` primary, `#7558b0` hover, `#5ec8c8` success, `#d4a060` warning,
  `#e05577` danger, `#e8e8f0` text, and `#8080a8` muted text;
- Inter/Open Sans fallback, 400/550/700 weights, and compact labels;
- the exact 250px sidebar, title/widget geometry, menu spacing, 4/5/8/10px radii,
  shadows, 150ms transitions, 1.01 hover scale, and Galaxy active glow;
- the exact dashboard `1280px` maximum width, responsive padding, typography hierarchy,
  `#0e1020` to `#111525` card gradient, borders, shadows, and card spacing;
- the fixed desktop sidebar and Galaxy drawer/underlay/menu-button behavior at 768px,
  plus the dashboard's 1180px, 768px, and 560px adaptations relevant to RAVE;
- visible keyboard focus and reduced-motion behavior retained as accessibility additions.

No logo, favicon, icon font, Arrow.js runtime, or font binary is copied. RAVE uses a
CSS/text mark and static vanilla JavaScript, requiring no Node runtime or build step.
This is not a claim of pixel-perfect equivalence for Galaxy components that RAVE does
not use, such as recordings, settings forms, tools, or modals.

## Licensing and redistribution

The inspected StarPilot root license is MIT. RAVE ports the relevant CSS declarations
and interaction metrics. The required upstream copyright and permission text is
preserved in [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md), which the
`rave-web` Debian package installs under `/usr/share/doc/rave-web/`. StarPilot
images/icons/fonts were not copied because their per-asset redistribution provenance
was not established. Before bundling any upstream asset, record its license and
include required notices in source and image output.

Future synchronization is an explicit review task; upstream changes must not silently
alter RAVE styling or invalidate this mapping.
