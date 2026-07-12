# Dashboard templates

Ready-to-paste Lovelace templates for the Resolume integration. Entity IDs
below use the placeholder host `127_0_0_1` and example layer/clip names —
replace them with your own (find yours under **Settings → Devices &
Services → Resolume → entities**, or start typing `resolume` in any
entity picker).

| File | What it gives you |
|------|-------------------|
| [mixer.yaml](mixer.yaml) | A row of live vertical faders — one per layer plus the composition master |
| [clip-deck.yaml](clip-deck.yaml) | A Resolume-style clip grid with thumbnails, tap to trigger |
| [performance.yaml](performance.yaml) | A full performance view: clip deck, mixer and a now-playing header combined |
| [now-playing.yaml](now-playing.yaml) | Template cards showing what's playing right now (no custom cards needed) |
| [auto-populated.yaml](auto-populated.yaml) | Mixer + clip deck that fill themselves in — no entity IDs to type (needs the `auto-entities` HACS card) |

To use one: open a dashboard → ✏️ Edit → **+ Add card → Manual** and paste
a card block, or ⋮ → **Raw configuration editor** to paste a whole view.
