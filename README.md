# Resolume Arena for Home Assistant

A Home Assistant custom integration that exposes
[Resolume Arena/Avenue](https://resolume.com) master faders — the
composition master and every layer master — as native slider entities,
kept in sync in real time in both directions.

## Features

- **Layer master sliders** — every layer's master fader becomes a
  `number` entity (0–100 %), plus one for the composition master.
- **Clip triggering with live thumbnails** — every clip in the grid
  becomes a `button` entity carrying its Resolume thumbnail and playing
  state; pressing it connects the clip, exactly like clicking it in
  Arena. The bundled **resolume-clip-card** shows the thumbnail with a
  green "connected" highlight and triggers on tap.
- **Real-time, bidirectional** — changes made in Resolume (or on a
  controller) push to Home Assistant instantly over the webserver's
  WebSocket channel; moving a slider in Home Assistant sets the parameter
  over REST. A 30-second REST resync acts as a safety net and picks up
  renamed, added, reordered or deleted layers.
- **Follows your composition** — entities take their names from the layer
  names in Resolume; new layers appear automatically without a restart,
  and faders for deleted layers become unavailable.
- **Config flow, diagnostics, device registry** — no YAML.

## Requirements

- Home Assistant 2025.1 or newer.
- Resolume Arena or Avenue 7.8+ with the webserver enabled:
  **Preferences → Webserver → Enable** (default port 8080). The REST API
  and its WebSocket channel share that port.

## Installation

### HACS

1. Add this repository as a custom repository (category: *Integration*).
2. Install **Resolume Arena** and restart Home Assistant.
3. **Settings → Devices & Services → Add Integration** → *Resolume Arena*,
   then enter the host and port of the machine running Resolume.

### Manual

Copy `custom_components/resolume` into `config/custom_components/` and
restart.

## Entities

One slider per fader, e.g.:

```text
number.resolume_<host>_composition_master   Composition master
number.resolume_<host>_background_master    Layer "Background" master
```

State is the fader position as a percentage (0–100). Attributes include
the raw Resolume value (typically 0.0–1.0), the layer index/id and the
parameter path.

Every non-empty clip slot becomes a button entity:

```text
button.resolume_<host>_intro_loop
```

Pressing it connects (triggers) the clip. Attributes: `clip_name`,
`layer_name`, `layer_index`, `clip_index`, `connected` (raw state) and
`playing` (boolean, pushed live). The clip's thumbnail is the entity
picture, proxied through Home Assistant so it also works via remote
access and the mobile apps; empty grid slots are skipped.

## The Resolume Clip Card

The card ships inside the integration and registers itself as a Lovelace
resource automatically (storage-mode dashboards):

```yaml
type: custom:resolume-clip-card
entity: button.resolume_127_0_0_1_intro_loop
```

It renders the live thumbnail with the clip name; a connected (playing)
clip gets Resolume's green highlight. Tap to trigger. Build a clip deck
with a grid:

```yaml
type: grid
columns: 4
cards:
  - type: custom:resolume-clip-card
    entity: button.resolume_127_0_0_1_intro_loop
  - type: custom:resolume-clip-card
    entity: button.resolume_127_0_0_1_main_visual
  # … one card per clip
```

If your dashboards are in YAML mode, add the resource manually:

```yaml
lovelace:
  resources:
    - url: /resolume_card/resolume-clip-card.js
      type: module
```

## Automations

```yaml
# Fade the composition in at showtime
automation:
  - alias: "Show start"
    trigger:
      - platform: time
        at: "20:00:00"
    action:
      - service: number.set_value
        target:
          entity_id: number.resolume_127_0_0_1_composition_master
        data:
          value: 100

# Dim a layer when the house lights come on
  - alias: "House lights dim FX layer"
    trigger:
      - platform: state
        entity_id: light.house
        to: "on"
    action:
      - service: number.set_value
        target:
          entity_id: number.resolume_127_0_0_1_fx_master
        data:
          value: 20
```

## How it works

```text
Resolume webserver (port 8080)
   │  GET /api/v1/composition        initial state + 30 s resync
   │  PUT /api/v1/parameter/by-id/…  slider moves from HA
   │  ws://host:8080/api/v1          subscribe → parameter_update pushes
   ▼
ResolumeCoordinator ── number entities (sliders)
```

The WebSocket reconnects automatically with exponential backoff; while it
is down, the periodic REST refresh keeps values eventually consistent.

## Debugging

```yaml
logger:
  logs:
    custom_components.resolume: debug
```

Diagnostics (with the host redacted) are downloadable from the device
page and include the product version, WebSocket state and all fader
values.

## Extending

The architecture mirrors the coordinator/client split used by the
companion integration: `api.py` (pure parsing/model), `client.py`
(REST + WebSocket), `coordinator.py` (single owner of the client),
`number.py` (thin entities). Additional parameters — layer opacity,
composition speed, crossfader, clip triggers — can be added by extending
`parse_composition()` with more paths and adding entities/platforms on
top of the same coordinator.

## License

[MIT](LICENSE)
