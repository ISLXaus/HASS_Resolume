/**
 * resolume-fader-card
 *
 * A vertical fader for Resolume master faders that streams value updates
 * to Arena live while you drag (throttled), instead of only on release
 * like Home Assistant's built-in slider.
 *
 * Configuration:
 *   type: custom:resolume-fader-card
 *   entity: number.resolume_127_0_0_1_background_master
 *   name: Background        # optional override
 */

const CARD_VERSION = "1.0.0";
const DRAG_SEND_INTERVAL_MS = 100; // ~10 updates/sec while dragging

class ResolumeFaderCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._dragging = false;
    this._dragValue = null;
    this._lastSent = 0;
    this._sendTimer = null;
    this._lastRender = null;
  }

  static getStubConfig(hass) {
    const entity =
      Object.keys(hass?.states || {}).find(
        (id) =>
          id.startsWith("number.") &&
          hass.states[id].attributes.parameter_path !== undefined
      ) || "number.resolume_master";
    return { entity };
  }

  static getConfigElement() {
    return document.createElement("resolume-fader-card-editor");
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("resolume-fader-card: 'entity' is required");
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
    return 4;
  }

  getGridOptions() {
    return { rows: 4, columns: 2, min_rows: 3, min_columns: 1 };
  }

  _stateObj() {
    return this._hass && this._config
      ? this._hass.states[this._config.entity]
      : undefined;
  }

  _currentValue() {
    // While dragging, the local value wins so the fader doesn't fight
    // the (slightly delayed) state coming back from Arena.
    if (this._dragging && this._dragValue !== null) return this._dragValue;
    const stateObj = this._stateObj();
    const value = stateObj ? parseFloat(stateObj.state) : NaN;
    return Number.isFinite(value) ? value : 0;
  }

  _render() {
    if (!this._config) return;
    const stateObj = this._stateObj();
    const unavailable = !stateObj || stateObj.state === "unavailable";
    const value = this._currentValue();
    const name =
      this._config.name ??
      stateObj?.attributes.friendly_name ??
      this._config.entity;

    const renderKey = JSON.stringify([
      this._config.entity, unavailable, Math.round(value * 10), name,
    ]);
    if (renderKey === this._lastRender && this.shadowRoot.firstChild) return;
    this._lastRender = renderKey;

    if (!this.shadowRoot.firstChild) this._buildDom();

    const wrap = this.shadowRoot.querySelector(".fader");
    wrap.classList.toggle("unavailable", unavailable);
    this.shadowRoot.querySelector(".fill").style.height = `${value}%`;
    this.shadowRoot.querySelector(".thumb").style.bottom = `${value}%`;
    this.shadowRoot.querySelector(".value").textContent = unavailable
      ? "—"
      : `${Math.round(value)}%`;
    this.shadowRoot.querySelector(".name").textContent = name;
    const track = this.shadowRoot.querySelector(".track");
    track.setAttribute("aria-valuenow", String(Math.round(value)));
    track.setAttribute("aria-label", name);
  }

  _buildDom() {
    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; height: 100%; }
      ha-card {
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 12px 8px;
        box-sizing: border-box;
      }
      .fader {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        width: 100%;
        min-height: 140px;
      }
      .fader.unavailable { opacity: 0.4; pointer-events: none; }
      .value {
        font: 600 14px -apple-system, BlinkMacSystemFont, "Segoe UI",
          Roboto, sans-serif;
        color: var(--primary-text-color);
        margin-bottom: 8px;
        font-variant-numeric: tabular-nums;
      }
      .track {
        position: relative;
        flex: 1;
        width: 36px;
        min-height: 100px;
        border-radius: 18px;
        background: var(--slider-track-color, rgba(120, 120, 120, 0.3));
        cursor: pointer;
        touch-action: none;
      }
      .fill {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        border-radius: 18px;
        background: #6fc22f; /* Resolume green */
        transition: height 0.05s linear;
      }
      .thumb {
        position: absolute;
        left: 50%;
        transform: translate(-50%, 50%);
        width: 44px;
        height: 18px;
        border-radius: 6px;
        background: var(--card-background-color, #fff);
        border: 1px solid rgba(0, 0, 0, 0.25);
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
        transition: bottom 0.05s linear;
        pointer-events: none;
      }
      .name {
        margin-top: 10px;
        font: 500 13px -apple-system, BlinkMacSystemFont, "Segoe UI",
          Roboto, sans-serif;
        color: var(--secondary-text-color);
        text-align: center;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 100%;
      }
    `;

    const card = document.createElement("ha-card");
    const fader = document.createElement("div");
    fader.className = "fader";
    const value = document.createElement("div");
    value.className = "value";
    const track = document.createElement("div");
    track.className = "track";
    track.setAttribute("role", "slider");
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("tabindex", "0");
    const fill = document.createElement("div");
    fill.className = "fill";
    const thumb = document.createElement("div");
    thumb.className = "thumb";
    track.append(fill, thumb);
    const name = document.createElement("div");
    name.className = "name";
    fader.append(value, track, name);
    card.appendChild(fader);

    track.addEventListener("pointerdown", (ev) => this._onPointerDown(ev));
    track.addEventListener("pointermove", (ev) => this._onPointerMove(ev));
    track.addEventListener("pointerup", (ev) => this._onPointerUp(ev));
    track.addEventListener("pointercancel", (ev) => this._onPointerUp(ev));
    track.addEventListener("keydown", (ev) => this._onKey(ev));

    this.shadowRoot.append(style, card);
  }

  _valueFromEvent(ev) {
    const track = this.shadowRoot.querySelector(".track");
    const rect = track.getBoundingClientRect();
    const ratio = 1 - (ev.clientY - rect.top) / rect.height;
    return Math.round(Math.min(Math.max(ratio * 100, 0), 100) * 10) / 10;
  }

  _onPointerDown(ev) {
    ev.preventDefault();
    ev.target.setPointerCapture?.(ev.pointerId);
    this._dragging = true;
    this._applyDrag(this._valueFromEvent(ev));
  }

  _onPointerMove(ev) {
    if (!this._dragging) return;
    ev.preventDefault();
    this._applyDrag(this._valueFromEvent(ev));
  }

  _onPointerUp(ev) {
    if (!this._dragging) return;
    ev.preventDefault();
    const value = this._valueFromEvent(ev);
    this._dragging = false;
    this._dragValue = null;
    window.clearTimeout(this._sendTimer);
    this._sendTimer = null;
    this._send(value); // always send the final position
    this._lastRender = null;
    this._render();
  }

  _onKey(ev) {
    const steps = { ArrowUp: 5, ArrowRight: 5, ArrowDown: -5, ArrowLeft: -5 };
    if (!(ev.key in steps)) return;
    ev.preventDefault();
    const value = Math.min(
      Math.max(this._currentValue() + steps[ev.key], 0),
      100
    );
    this._send(value);
  }

  _applyDrag(value) {
    this._dragValue = value;
    this._lastRender = null;
    this._render();

    // Throttle: send immediately if the interval has passed, otherwise
    // schedule a trailing send so the last movement always lands.
    const now = Date.now();
    if (now - this._lastSent >= DRAG_SEND_INTERVAL_MS) {
      this._send(value);
    } else if (this._sendTimer === null) {
      this._sendTimer = window.setTimeout(() => {
        this._sendTimer = null;
        if (this._dragging && this._dragValue !== null) {
          this._send(this._dragValue);
        }
      }, DRAG_SEND_INTERVAL_MS);
    }
  }

  _send(value) {
    if (!this._hass || !this._config) return;
    this._lastSent = Date.now();
    this._hass.callService("number", "set_value", {
      entity_id: this._config.entity,
      value: Math.round(value),
    });
  }
}

class ResolumeFaderCardEditor extends HTMLElement {
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
        ({ entity: "Resolume fader entity", name: "Name (optional)" })[
          schema.name
        ] ?? schema.name;
      this._form.addEventListener("value-changed", (ev) => {
        const config = {
          type: "custom:resolume-fader-card",
          ...ev.detail.value,
        };
        if (!config.name) delete config.name;
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
    this._form.data = {
      entity: this._config?.entity || "",
      name: this._config?.name || "",
    };
    this._form.schema = [
      {
        name: "entity",
        required: true,
        selector: {
          entity: { filter: [{ integration: "resolume", domain: "number" }] },
        },
      },
      { name: "name", selector: { text: {} } },
    ];
  }
}

if (!customElements.get("resolume-fader-card")) {
  customElements.define("resolume-fader-card", ResolumeFaderCard);
  customElements.define("resolume-fader-card-editor", ResolumeFaderCardEditor);

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "resolume-fader-card",
    name: "Resolume Fader Card",
    description:
      "Vertical fader that streams live updates to Resolume while dragging.",
    preview: true,
    documentationURL: "https://github.com/ianscott/resolume-homeassistant",
  });

  console.info(
    `%c RESOLUME-FADER-CARD %c v${CARD_VERSION} `,
    "background: #6fc22f; color: black; font-weight: 700;",
    "background: #333; color: white;"
  );
}
