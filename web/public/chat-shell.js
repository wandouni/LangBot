/* Standalone chat page bootstrapper.
 *
 * /chat.html, /chat-jishi.html and /default.html are thin wrappers around this
 * script: each page declares a small JSON config block and this script turns
 * it into the LangBot embed widget expanded to the full viewport.
 *
 * Config precedence (low to high):
 *   1. <script type="application/json" id="chat-config"> inline defaults
 *   2. ?config=<http(s) url> remote JSON, merged over the inline defaults
 *   3. URL parameters: embed, title, theme (alias of accent)
 *   4. #preview=<encoded roles>&previewWelcome=<encoded text> from the
 *      admin test page (unsaved draft override)
 *
 * Vite copies web/public into web/dist, so the core serves this file at
 * /chat-shell.js and the widget URL stays same-origin -- no host or scheme
 * needs to be hard-coded.
 */
(function () {
  'use strict';

  // Height reserved at the bottom for the launcher bubble: 20px offset +
  // 56px bubble. Adjust to change the gap under the panel.
  var BUBBLE_RESERVED = 76;
  var HEX_COLOR = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
  var BOT_UUID = /^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$/;
  var DEFAULT_TITLE = 'LangBot';

  function readInlineConfig() {
    var el = document.getElementById('chat-config');
    if (!el) return {};
    try {
      var parsed = JSON.parse(el.textContent || '{}');
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch (e) {
      console.warn('[chat-shell] invalid inline config, ignoring it');
      return {};
    }
  }

  function applyQueryOverrides(config, params) {
    var embed = params.get('embed');
    if (embed && BOT_UUID.test(embed)) config.bot = embed;
    var title = params.get('title');
    if (title) config.title = title.slice(0, 120);
    var theme = params.get('theme') || params.get('accent');
    if (theme && HEX_COLOR.test(theme)) config.accent = theme;
    return config;
  }

  // The admin "test page" menu appends the unsaved quick-question draft as a
  // URL hash: #preview=<encoded JSON array>. A hash is used instead of a query
  // parameter because it is not sent to the server and can carry a full draft.
  // Returns null when the page was opened normally; [] is a real preview that
  // must hide every suggestion tab.
  function readPreviewRoles() {
    var hash = window.location.hash || '';
    if (!hash) return null;
    var params = new URLSearchParams(hash.replace(/^#/, ''));
    if (!params.has('preview')) return null;
    try {
      var parsed = JSON.parse(params.get('preview') || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      console.warn('[chat-shell] invalid quick-question preview, ignoring it');
      return [];
    }
  }

  // The same hash also carries the unsaved welcome message as
  // #previewWelcome=<encoded text>. Returns null when the page was opened
  // normally; an empty string is a real preview that clears the welcome text.
  function readPreviewWelcome() {
    var hash = window.location.hash || '';
    if (!hash) return null;
    var params = new URLSearchParams(hash.replace(/^#/, ''));
    if (!params.has('previewWelcome')) return null;
    return params.get('previewWelcome') || '';
  }

  function setAttr(el, name, value) {
    if (typeof value === 'string' && value) el.setAttribute(name, value);
  }

  function start(config) {
    if (!config || typeof config.bot !== 'string' || !config.bot) {
      console.error('[chat-shell] chat config has no bot uuid');
      return;
    }
    var title = config.title || DEFAULT_TITLE;
    document.title = title;
    if (config.locale) document.documentElement.lang = config.locale;

    // The widget endpoint is cached for five minutes. The admin "test page"
    // menu appends an opaque ?v= value so a freshly saved bot configuration
    // is visible immediately instead of waiting for the cache to expire.
    var cacheVersion = new URLSearchParams(window.location.search).get('v');

    var script = document.createElement('script');
    script.src =
      '/api/v1/embed/' +
      encodeURIComponent(config.bot) +
      '/widget.js' +
      (cacheVersion ? '?v=' + encodeURIComponent(cacheVersion) : '');
    setAttr(script, 'data-title', title);
    // The page has no content of its own, so an unopened panel would leave the
    // visitor staring at a blank screen.
    script.setAttribute('data-auto-open', 'true');
    setAttr(script, 'data-accent', config.accent);
    setAttr(script, 'data-accent-hover', config.accentHover);
    setAttr(script, 'data-accent-border', config.accentBorder);
    setAttr(script, 'data-accent-soft', config.accentSoft);
    setAttr(script, 'data-on-accent', config.onAccent);
    setAttr(script, 'data-logo', config.logo);
    setAttr(script, 'data-subtitle', config.subtitle);
    // Preview an unsaved welcome message from the admin test page. An empty
    // draft must clear the saved text, so the flag is set even without data.
    var previewWelcome = readPreviewWelcome();
    if (previewWelcome !== null) {
      script.setAttribute('data-preview-welcome', 'true');
      setAttr(script, 'data-welcome', previewWelcome);
    }
    // Page-level roles are no longer a fallback. Only an explicit preview
    // (the admin test page) may override the saved bot groups, and an empty
    // preview must remain empty instead of reusing the saved groups.
    var previewRoles = readPreviewRoles();
    if (previewRoles !== null) {
      script.setAttribute('data-preview-roles', 'true');
      if (previewRoles.length) {
        script.setAttribute('data-roles', JSON.stringify(previewRoles));
      }
    }
    document.head.appendChild(script);

    installLayoutOverride();
  }

  // The widget renders inside a Shadow DOM, so a plain <style> on the page
  // cannot reach its panel. Append an override stylesheet to the widget's
  // shadow root instead; it lands after the widget's own styles and wins on
  // equal specificity.
  function installLayoutOverride() {
    var OVERRIDE_CSS =
      '.lb-panel {' +
      '  left: 0;' +
      '  right: 0;' +
      '  width: auto;' +
      '  bottom: ' +
      BUBBLE_RESERVED +
      'px;' +
      '  height: calc(100vh - ' +
      BUBBLE_RESERVED +
      'px);' +
      '  max-height: calc(100vh - ' +
      BUBBLE_RESERVED +
      'px);' +
      '  border-radius: 0;' +
      '}' +
      // Standalone consultation pages carry the school's own branding, so the
      // "Powered by LangBot" line is hidden here only; embedded widgets on
      // other sites keep it.
      '.lb-footer { display: none; }';

    function apply() {
      var root = document.getElementById('langbot-widget-root');
      if (!root || !root.shadowRoot) return false;
      if (root.shadowRoot.querySelector('style[data-layout-override]')) {
        return true;
      }
      var style = document.createElement('style');
      style.setAttribute('data-layout-override', '');
      style.textContent = OVERRIDE_CSS;
      root.shadowRoot.appendChild(style);
      return true;
    }

    if (apply()) return;
    document.addEventListener('DOMContentLoaded', apply);
    var tries = 0;
    var timer = setInterval(function () {
      if (apply() || ++tries > 100) clearInterval(timer);
    }, 50);
  }

  function boot() {
    var params = new URLSearchParams(window.location.search);
    var config = readInlineConfig();
    var remote = params.get('config');

    function launch() {
      applyQueryOverrides(config, params);
      start(config);
    }

    if (!remote || !/^https?:\/\//i.test(remote)) {
      launch();
      return;
    }

    fetch(remote, { credentials: 'omit' })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (data && typeof data === 'object') {
          Object.keys(data).forEach(function (key) {
            config[key] = data[key];
          });
        }
      })
      .catch(function () {
        // A broken remote config must not take the page down.
        console.warn('[chat-shell] could not load ' + remote);
      })
      .then(launch);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
