/**
 * resolume-clip-card
 *
 * Renders a Resolume clip with its live thumbnail and name; tap to
 * connect (trigger) the clip, exactly like clicking it in Arena.
 * A playing clip gets Resolume's green highlight.
 *
 * Configuration:
 *   type: custom:resolume-clip-card
 *   entity: button.resolume_127_0_0_1_my_clip
 */

const CARD_VERSION = "1.0.0";

class ResolumeClipCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._lastRender = null;
  }

  static getStubConfig(hass) {
    const entity =
      Object.keys(hass?.states || {}).find(
        (id) =>
          id.startsWith("button.") &&
          hass.states[id].attributes.clip_index !== undefined
      ) || "button.resolume_clip";
    return { entity };
  }

  static getConfigElement() {
    return document.createElement("resolume-clip-card-editor");
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("resolume-clip-card: 'entity' is required");
    }
    this._config = config;
    this._lastRender = null;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 2;
  }

  getGridOptions() {
    return { rows: 2, columns: 3, min_rows: 2, min_columns: 2 };
  }

  _stateObj() {
    return this._hass && this._config
      ? this._hass.states[this._config.entity]
      : undefined;
  }

  _render() {
    if (!this._config) return;
    const stateObj = this._stateObj();
    const a = stateObj ? stateObj.attributes : {};

    const unavailable = !stateObj || stateObj.state === "unavailable";
    const name = this._config.name ?? a.clip_name ?? "Clip";
    const picture = a.entity_picture || "";
    const playing = a.playing === true;

    const renderKey = JSON.stringify([
      this._config.entity, unavailable, name, picture, playing,
    ]);
    if (renderKey === this._lastRender && this.shadowRoot.firstChild) return;
    this._lastRender = renderKey;

    if (!this.shadowRoot.firstChild) this._buildDom();

    const tile = this.shadowRoot.querySelector(".clip");
    const img = this.shadowRoot.querySelector("img");
    const label = this.shadowRoot.querySelector(".name");

    tile.classList.toggle("unavailable", unavailable);
    tile.classList.toggle("playing", playing);
    if (picture && img.getAttribute("src") !== picture) {
      img.src = picture;
    }
    img.style.display = picture && !unavailable ? "" : "none";
    label.textContent = unavailable ? "unavailable" : name;
    tile.setAttribute("aria-label", `Trigger clip ${name}`);
  }

  _buildDom() {
    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; height: 100%; }
      ha-card {
        height: 100%;
        overflow: hidden;
        padding: 0;
      }
      .clip {
        position: relative;
        width: 100%;
        height: 100%;
        min-height: 80px;
        background: #111;
        cursor: pointer;
        user-select: none;
        -webkit-user-select: none;
        -webkit-tap-highlight-color: transparent;
        border: 2px solid transparent;
        border-radius: var(--ha-card-border-radius, 12px);
        box-sizing: border-box;
        transition: border-color 0.15s ease, filter 0.1s ease;
      }
      .clip.playing {
        border-color: #6fc22f; /* Resolume's connected green */
        box-shadow: 0 0 8px rgba(111, 194, 47, 0.6);
      }
      .clip.unavailable { cursor: not-allowed; filter: grayscale(1) brightness(0.5); }
      .clip:active:not(.unavailable) { filter: brightness(1.4); }
      img {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: inherit;
      }
      .name {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 4px 6px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
          Roboto, sans-serif;
        font-size: 12px;
        font-weight: 500;
        line-height: 1.2;
        color: #fff;
        background: linear-gradient(transparent, rgba(0, 0, 0, 0.75));
        border-radius: 0 0 inherit inherit;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        text-align: center;
      }
      .playing .name::before {
        content: "▶ ";
        color: #6fc22f;
      }
    `;

    const card = document.createElement("ha-card");
    const tile = document.createElement("div");
    tile.className = "clip";
    tile.setAttribute("role", "button");
    tile.setAttribute("tabindex", "0");
    const img = document.createElement("img");
    img.alt = "";
    const name = document.createElement("div");
    name.className = "name";
    tile.append(img, name);
    card.appendChild(tile);

    const trigger = () => {
      const stateObj = this._stateObj();
      if (!stateObj || stateObj.state === "unavailable") return;
      this._hass.callService("button", "press", {
        entity_id: this._config.entity,
      });
    };
    tile.addEventListener("click", trigger);
    tile.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        trigger();
      }
    });

    this.shadowRoot.append(style, card);
  }
}

class ResolumeClipCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (schema) =>
        schema.name === "entity" ? "Resolume clip entity" : schema.name;
      this._form.addEventListener("value-changed", (ev) => {
        const config = { type: "custom:resolume-clip-card", ...ev.detail.value };
        this.dispatchEvent(
          new CustomEvent("config-changed", {
            detail: { config },
            bubbles: true,
            composed: true,
          })
        );
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = { entity: this._config?.entity || "" };
    this._form.schema = [
      {
        name: "entity",
        required: true,
        selector: {
          entity: { filter: [{ integration: "resolume", domain: "button" }] },
        },
      },
    ];
  }
}

if (!customElements.get("resolume-clip-card")) {
  customElements.define("resolume-clip-card", ResolumeClipCard);
  customElements.define("resolume-clip-card-editor", ResolumeClipCardEditor);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "resolume-clip-card",
    name: "Resolume Clip Card",
    description: "Trigger a Resolume clip with its live thumbnail.",
    preview: true,
    documentationURL: "https://github.com/ianscott/resolume-homeassistant",
  });

  console.info(
    `%c RESOLUME-CLIP-CARD %c v${CARD_VERSION} `,
    "background: #6fc22f; color: black; font-weight: 700;",
    "background: #333; color: white;"
  );
}
