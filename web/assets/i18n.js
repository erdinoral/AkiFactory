/* Arayuz dili (TR / EN). Metinler kodda Turkce; EN secilince sayfa sozlukle cevrilir.
   Sozluk: /assets/i18n/en.json — guncellemek icin: python scripts/build_ui_i18n.py */
(function () {
  "use strict";
  var KEY = "aki_ui_lang";
  var ATTRS = ["placeholder", "title", "aria-label", "data-help", "alt"];
  var SEP = /( · | — | – | \| | \/ |: )/;
  var SKIP = "script,style,code,pre,textarea,[data-no-i18n],[contenteditable='true']";
  var SKIP_ATTR = "script,style,[data-no-i18n]";
  var dict = null;
  // "Bu niste {0} konu..." gibi sablon anahtarlari (app.js `${n}` metinleri)
  var templates = [];
  var lang = localStorage.getItem(KEY) === "en" ? "en" : "tr";
  var textRec = new WeakMap();
  var attrRec = new WeakMap();
  var observer = null;

  function norm(s) {
    return String(s).replace(/\s+/g, " ").trim();
  }

  function buildTemplates(d) {
    var esc = function (s) {
      return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    };
    return Object.keys(d)
      .filter(function (k) {
        return /\{\d\}/.test(k) && k.replace(/\{\d\}/g, "").replace(/[^A-Za-z\u00C0-\u017F]/g, "").length >= 4;
      })
      .map(function (k) {
        var order = [];
        var letter = /[A-Za-z\u00C0-\u017F]/;
        var bits = k.split(/(\{\d\})/);
        var src = bits.map(function (p, i) {
          var m = p.match(/^\{(\d)\}$/);
          if (!m) return esc(p);
          order.push(+m[1]);
          // "Hazir{0}" kelimeye yapisik: "Hazirlaniyor" icinde eslesmesin
          var glueL = letter.test((bits[i - 1] || "").slice(-1));
          var glueR = letter.test((bits[i + 1] || "").charAt(0));
          var L = "[^A-Za-z\\u00C0-\\u017F]";
          if (glueL && glueR) return "(" + L + ".*?" + L + "|" + L + ")";
          if (glueL) return "(" + L + ".*?)";
          if (glueR) return "(.*?" + L + ")";
          return "(.+?)";
        });
        return { re: new RegExp("^" + src.join("") + "$"), order: order, en: d[k], lit: k.length - order.length * 3 };
      })
      .sort(function (a, b) {
        return b.lit - a.lit;
      });
  }

  // tight: degisken kisim sabit metinden uzunsa reddet ("Son uretim: {0}" tum satiri yutmasin)
  function templateEn(s, depth, tight) {
    for (var i = 0; i < templates.length; i++) {
      var tp = templates[i];
      var m = s.match(tp.re);
      if (!m) continue;
      if (tight && m.slice(1).join("").length > tp.lit) continue;
      var vals = {};
      tp.order.forEach(function (slot, j) {
        var v = m[j + 1];
        vals[slot] = (depth < 1 && toEn(v, depth + 1)) || v;
      });
      return tp.en.replace(/\{(\d)\}/g, function (all, slot) {
        return slot in vals ? vals[slot] : all;
      });
    }
    return null;
  }

  // "gemini hazir" gibi: degisken + sabit metin (bastan / sondan bir kelime ayir)
  function partEn(p, depth) {
    var s = p.trim();
    if (dict[s]) return dict[s];
    var tpl = templateEn(s, depth || 0);
    if (tpl) return tpl;
    var paren = s.match(/^(.+?)(\s*\([^()]*\)[.…]?)$/);
    if (paren && dict[paren[1]]) return dict[paren[1]] + paren[2];
    var m = s.match(/^(\S+)\s+(.+)$/);
    if (m && dict[m[2]]) return m[1] + " " + dict[m[2]];
    m = s.match(/^(.+)\s+(\S+)$/);
    if (m && dict[m[1]]) return dict[m[1]] + " " + m[2];
    return null;
  }

  function toEn(raw, depth) {
    var n = norm(raw);
    if (!n || !dict) return null;
    if (dict[n]) return dict[n];
    var whole = templateEn(n, depth || 0, true);
    if (whole) return whole;
    var parts = n.split(SEP);
    if (parts.length < 3) return partEn(n, depth);
    var hit = false;
    var out = parts.map(function (p, i) {
      if (i % 2) return p;
      var t = partEn(p, depth);
      if (t) hit = true;
      return t || p;
    });
    return hit ? out.join("") : templateEn(n, depth || 0);
  }

  function withSpace(orig, t) {
    return orig.match(/^\s*/)[0] + t + orig.match(/\s*$/)[0];
  }

  function skipped(el) {
    return !el || !!el.closest(SKIP);
  }

  function doText(node) {
    var cur = node.nodeValue;
    var rec = textRec.get(node);
    if (rec && (cur === rec.en || cur === rec.tr)) {
      var want = lang === "en" ? rec.en : rec.tr;
      if (cur !== want) node.nodeValue = want;
      return;
    }
    textRec.delete(node);
    if (lang !== "en" || !/\S/.test(cur) || skipped(node.parentElement)) return;
    var en = toEn(cur);
    if (!en) return;
    var full = withSpace(cur, en);
    textRec.set(node, { tr: cur, en: full });
    node.nodeValue = full;
  }

  function doAttrs(el) {
    if (!el || el.closest(SKIP_ATTR)) return;
    var recs = attrRec.get(el) || {};
    ATTRS.forEach(function (a) {
      if (!el.hasAttribute(a)) return;
      var cur = el.getAttribute(a);
      var rec = recs[a];
      if (rec && (cur === rec.en || cur === rec.tr)) {
        var want = lang === "en" ? rec.en : rec.tr;
        if (cur !== want) el.setAttribute(a, want);
        return;
      }
      delete recs[a];
      if (lang !== "en") return;
      var en = toEn(cur);
      if (!en) return;
      recs[a] = { tr: cur, en: en };
      el.setAttribute(a, en);
    });
    attrRec.set(el, recs);
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) return doText(root);
    if (root.nodeType !== 1 && root.nodeType !== 9) return;
    if (root.nodeType === 1) doAttrs(root);
    var tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    var n;
    while ((n = tw.nextNode())) {
      if (n.nodeType === 3) doText(n);
      else doAttrs(n);
    }
  }

  function observe(on) {
    if (on && !observer) {
      observer = new MutationObserver(function (muts) {
        muts.forEach(function (m) {
          if (m.type === "characterData") doText(m.target);
          else if (m.type === "attributes") doAttrs(m.target);
          else m.addedNodes.forEach(walk);
        });
      });
      observer.observe(document.body, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ATTRS,
      });
    } else if (!on && observer) {
      observer.disconnect();
      observer = null;
    }
  }

  function loadDict() {
    if (dict) return Promise.resolve(dict);
    return fetch("/assets/i18n/en.json", { cache: "no-store" })
      .then(function (r) {
        return r.ok ? r.json() : {};
      })
      .catch(function () {
        return {};
      })
      .then(function (d) {
        dict = d || {};
        templates = buildTemplates(dict);
        return dict;
      });
  }

  function syncSwitch() {
    document.documentElement.lang = lang;
    document.querySelectorAll(".ios-lang-switch").forEach(function (w) {
      w.classList.toggle("is-en", lang === "en");
      var t = w.querySelector("[role=switch]");
      if (t) t.setAttribute("aria-checked", lang === "en" ? "true" : "false");
    });
  }

  function setLang(next) {
    lang = next === "en" ? "en" : "tr";
    localStorage.setItem(KEY, lang);
    syncSwitch();
    return (lang === "en" ? loadDict() : Promise.resolve(dict)).then(function () {
      walk(document.body);
      observe(lang === "en");
      document.dispatchEvent(new CustomEvent("aki:lang", { detail: { lang: lang } }));
    });
  }

  function t(text) {
    return lang === "en" ? toEn(text) || text : text;
  }

  window.akiI18n = { setLang: setLang, getLang: function () { return lang; }, t: t };

  function init() {
    document.querySelectorAll(".ios-lang-switch").forEach(function (w) {
      w.addEventListener("click", function (e) {
        var pick = e.target.closest("[data-ui-lang]");
        setLang(pick ? pick.dataset.uiLang : lang === "en" ? "tr" : "en");
      });
    });
    syncSwitch();
    if (lang === "en") setLang("en");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
