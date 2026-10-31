/* Français / anglais. Les données restent en français (clés) ; l'affichage traduit via labels.json.
   t(texte, {param}) : texte d'interface ; v(valeur) : valeur de donnée (type, couleur, matière, forme...). */
(function () {
  var KEY = "veille:lang";
  var data = { values: {}, ui: {} };
  var extra = {}; // traductions de détails libres, fournies par stats.json
  var lang = "fr";
  var listeners = [];

  try {
    var saved = localStorage.getItem(KEY);
    lang = saved === "en" || saved === "fr" ? saved : "fr";
  } catch (e) {}

  function fill(text, params) {
    return String(text).replace(/\{(\w+)\}/g, function (m, k) { return params && params[k] != null ? params[k] : m; });
  }
  function t(fr, params) {
    var s = lang === "en" && data.ui[fr] ? data.ui[fr] : fr;
    return fill(s, params);
  }
  function v(value) {
    if (value == null) return "";
    var s = String(value);
    if (lang !== "en") return s;
    if (s.indexOf(" · ") > -1) return s.split(" · ").map(v).join(" · "); // « Jupes · midi »
    var hit = data.values[s] || extra[s];
    if (hit) return hit;
    var low = s.toLowerCase(); // « Noir » (palette) retrouve « noir »
    hit = low !== s ? data.values[low] || extra[low] : "";
    return hit ? hit.charAt(0).toUpperCase() + hit.slice(1) : s;
  }
  function d(value) { // détail libre (« volants ») : sa traduction propre prime sur celle d'une forme
    var s = String(value == null ? "" : value);
    return lang === "en" ? (extra[s] || data.values[s] || s) : s;
  }
  function locale() { return lang === "en" ? "en-CA" : "fr-CA"; }
  function setExtra(map) { extra = map && typeof map === "object" ? map : {}; }

  function applyStatic() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t(el.getAttribute("data-i18n")); });
    var title = document.documentElement.getAttribute("data-title");
    if (title) document.title = t(title);
    document.querySelectorAll(".lang button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-lang") === lang));
    });
  }
  function setLang(next) {
    if (next !== "fr" && next !== "en") return;
    lang = next;
    try { localStorage.setItem(KEY, lang); } catch (e) {}
    applyStatic();
    listeners.forEach(function (fn) { fn(lang); });
  }
  function onChange(fn) { listeners.push(fn); }

  function mount() {
    var host = document.querySelector(".head-right");
    if (host && !host.querySelector(".lang")) {
      var box = document.createElement("div");
      box.className = "lang";
      box.setAttribute("role", "group");
      box.setAttribute("aria-label", "Langue / Language");
      ["fr", "en"].forEach(function (code) {
        var b = document.createElement("button");
        b.type = "button";
        b.setAttribute("data-lang", code);
        b.textContent = code.toUpperCase();
        b.addEventListener("click", function () { setLang(code); });
        box.appendChild(b);
      });
      host.insertBefore(box, host.firstChild);
    }
    applyStatic();
  }

  function load() {
    return fetch("labels.json", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (json) {
        if (json && typeof json === "object") data = { values: json.values || {}, ui: json.ui || {} };
        mount();
      });
  }

  window.I18N = { t: t, v: v, d: d, lang: function () { return lang; }, locale: locale, setLang: setLang, onChange: onChange, setExtra: setExtra, load: load };
})();
