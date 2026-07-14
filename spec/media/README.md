# AiraCare — Brand / Media Assets

Logo and brand mark for **AiraCare** — Hybrid Edge–Foundry Agent for Alzheimer's Home Care.

## Files
| File | Use |
|---|---|
| `airacare-mark.svg` / `.png` | Icon-only mark (app icon, favicon, avatar). 256×256, transparent. |
| `airacare-logo.svg` / `.png` | Full horizontal lockup on light backgrounds. 720×220, transparent. |
| `airacare-logo-dark.svg` / `.png` | Full lockup on dark backgrounds (rounded dark card). |

PNGs are rendered at 2× for crisp use in slides/docs. SVGs are the source of truth — edit those and re-render if needed.

## Concept
- **Guardian halo / aura ring** — an open ring (not a closed cage) = watching over, without confinement. The name *Aira* evokes an airy, calm presence.
- **Home + care-pulse** — a protective home enclosing a heartbeat line = in-home care + vital monitoring.
- **Warm accent dot** (amber) — the person being cared for, held within the aura.
- The ring gradient **teal → blue → indigo** carries the hybrid story: teal (edge) flowing into blue/indigo (cloud/Foundry).

## Colors
| Token | Hex |
|---|---|
| Edge teal | `#3FC8C0` |
| Foundry blue | `#3B82F6` |
| Cloud indigo | `#6366F1` |
| Warm accent | `#FFB454` |
| Ink (wordmark) | `#1E293B` |
| Muted text | `#64748B` |

## Tagline
> **Watches on the edge. Thinks in the cloud.**

## Re-rendering PNGs
Rendered via Playwright Chromium (transparent background). To regenerate, load each
SVG in a transparent HTML page at its native size with `device_scale_factor=2` and
screenshot with `omit_background=True`.
