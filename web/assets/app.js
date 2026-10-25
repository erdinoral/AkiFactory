const $ = (id) => document.getElementById(id);

const LANG_KEY = "aki_production_lang";
const TTS_KEY = "aki_tts_engine";
const PLATFORM_KEY = "aki_platform";
const NICHE_KEY = "aki_niche";
const RVC_VOICE_KEY = "aki_rvc_voice";
const OUTRO_KEY = "aki_outro";
const EDITOR_KEY = "aki_editor_model";
const WRITER_KEY = "aki_writer_model";
const DUAL_LLM_KEY = "aki_dual_llm";
const EDITOR_WEB_VERIFY_KEY = "aki_editor_web_verify";
const ANALYZE_VISION_KEY = "aki_analyze_vision_model";
const LAST_VOICE_KEY = "aki_last_voice";
const VOICE_MALE_MIGRATE_KEY = "aki_voice_male_v3";
const VOICE_RVC_FIX_KEY = "aki_voice_rvc_v4";
const EDITOR_9B_MIGRATE_KEY = "aki_editor_prefer_9b_v1";
const QUEUE_NOTIFY_KEY = "aki_queue_notify_v1";
const PRODUCE_SUBTAB_KEY = "aki_produce_subtab";
const PRODUCE_SUBTABS = ["short", "long", "produced"];
const SETTINGS_SUBTAB_KEY = "aki_settings_subtab";
const SETTINGS_SUBTABS = ["system", "api", "telegram", "hooks", "files"];
const SETTINGS_HEAD_HINTS = {
  system: "Ollama, GPU ve ilk kurulum kontrolleri.",
  api: "Pexels ve Pixabay stok video API anahtarlari.",
  telegram: "Video bitince telefonuna Telegram bildirimi.",
  hooks: "Nis basina hook ornekleri ve LLM hafizasi.",
  files: "RVC ses, arka plan muzigi ve kanal outrolari.",
};
const DUAL_SECOND_LANG_KEY = "aki_dual_second_lang";

let pollTimer = null;
let queuePollTimer = null;
let lastArchivedTask = null;
const archivedTaskIds = new Set();
const notifyRecentKeys = new Map();
const NOTIFY_DEDUP_MS = 90000;
let appConfig = null;
let pendingScript = "";
let ollamaRunning = false;
let ollamaModelOk = true;
let ollamaModelError = "";
let backendReachable = false;
let engineReady = false;
let healthFailStreak = 0;
const HEALTH_FAIL_BEFORE_DOWN = 3;
let queueActive = false;
/** Kullanici Durdur dedi — hayalet engine_busy ile "devam ediyor" gosterme. */
let suppressQueueBusyUi = false;
let queueWorkerAlive = true;
let queuePollLastCurrent = null;
let loadConfigPromise = null;
let currentBatchId = null;
let currentLongformId = null;
let outputFocusRefId = null;
let outputFocusKind = null;
let longformPollTimer = null;
let longformChapters = [];
const archivedLongformTasks = new Set();
const archivedBatchTasks = new Set();
const finalizedQueueJobs = new Set();
let currentVideoUrl = "";
let currentVideoName = "akifactory.mp4";
let previewAutoplay = true;
let outputGalleryId = null;
let lastPublishPack = null;
let galleryItemsCache = [];
let longformGalleryCache = [];
let galleryViewMode = "short";
let gallerySelectedIds = new Set();
let galleryBulkDeleting = false;
let analyzeGalleryCache = [];
let analyzeRunning = false;
let analyzeImageObjectUrls = [];
let galleryDetailItem = null;
let galleryShareTipsLoading = false;
let galleryPublishPackLoading = false;
let galleryFooocusLoading = false;
let galleryWangpLoading = false;
const publishPackBackfillQueued = new Set();
const publishPackBackfillDone = new Set();
let publishPackBackfillRunning = false;
let galleryEnTitlesFixStarted = false;
let previewZoom = 1;
let previewExpanded = false;
let currentDraftId = null;
let currentLongformDraftId = null;
let currentTaskId = null;
let currentDualTaskId = null;
let generateAbortController = null;
let productionCancelled = false;
let productionMode = null;
let queueCompletionNotified = false;
let stopProductionInFlight = false;

const PREVIEW_ZOOM_MIN = 0.75;
const PREVIEW_ZOOM_MAX = 2.5;
const PREVIEW_ZOOM_STEP = 0.25;

const STARTUP_STEPS = [
  "Python ortami hazirlaniyor...",
  "Video motoru baslatiliyor...",
  "Modeller yukleniyor...",
  "Neredeyse hazir...",
];
const HEALTH_MAX_RETRIES = 24;
const HEALTH_INTERVAL_MS = 5000;
const STEP_ADVANCE_MS = 30000;

const PREVIEW_CLASSES = {
  tiktok_classic: "sub-preview-tiktok",
  youtube: "sub-preview-youtube",
  minimal: "sub-preview-minimal",
  off: "sub-preview-off",
  custom: "sub-preview-custom",
};

let ignoreCustomSelectDocClose = false;
let selectBackdropEl = null;

function ensureSelectBackdrop() {
  if (selectBackdropEl) return selectBackdropEl;
  const bd = document.createElement("div");
  bd.className = "aki-select-backdrop";
  bd.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    e.stopPropagation();
    closeAllCustomSelects();
  });
  bd.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
  selectBackdropEl = bd;
  return bd;
}

function resetCustomSelectMenuPosition(menu) {
  if (!menu) return;
  menu.style.position = "";
  menu.style.left = "";
  menu.style.top = "";
  menu.style.bottom = "";
  menu.style.right = "";
  menu.style.width = "";
  menu.style.maxHeight = "";
  menu.style.zIndex = "";
}

function positionCustomSelectMenu(select) {
  const menu = select._akiMenu;
  const trigger = select._akiTrigger;
  if (!menu || !trigger) return;

  const bd = ensureSelectBackdrop();
  // Her acilista sirayi garantile: once backdrop, sonra menu (ustte)
  document.body.appendChild(bd);
  document.body.appendChild(menu);

  const rect = trigger.getBoundingClientRect();
  const gap = 6;
  const maxMenuH = 280;
  const wasHidden = menu.hidden;
  menu.hidden = false;
  const naturalH = Math.max(menu.scrollHeight || 0, 120);
  if (wasHidden) menu.hidden = true;
  const spaceBelow = window.innerHeight - rect.bottom - gap;
  const spaceAbove = rect.top - gap;
  const openBelow = spaceBelow >= 140 || spaceBelow >= spaceAbove;
  const avail = Math.max(120, openBelow ? spaceBelow - 4 : spaceAbove - 4);
  const menuMax = Math.min(maxMenuH, avail, Math.max(naturalH, 120));

  menu.style.position = "fixed";
  menu.style.left = `${Math.max(8, rect.left)}px`;
  menu.style.right = "auto";
  menu.style.width = `${Math.max(rect.width, 200)}px`;
  menu.style.zIndex = "10050";
  menu.style.maxHeight = `${menuMax}px`;
  menu.style.overflowY = "auto";

  if (openBelow) {
    menu.style.top = `${rect.bottom + gap}px`;
    menu.style.bottom = "auto";
  } else {
    menu.style.top = "auto";
    menu.style.bottom = `${window.innerHeight - rect.top + gap}px`;
  }
}

let selectPositionRaf = null;
function scheduleRepositionOpenSelects() {
  if (selectPositionRaf) return;
  selectPositionRaf = requestAnimationFrame(() => {
    selectPositionRaf = null;
    document.querySelectorAll(".aki-select.open").forEach((wrap) => {
      const select = wrap.querySelector("select.aki-select-native");
      if (select) positionCustomSelectMenu(select);
    });
  });
}

function closeAllCustomSelects() {
  document.querySelectorAll(".aki-select.open").forEach((wrap) => {
    wrap.classList.remove("open");
    const trigger = wrap.querySelector(".aki-select-trigger");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  });
  document.querySelectorAll(".aki-select-menu").forEach((menu) => {
    menu.hidden = true;
    resetCustomSelectMenuPosition(menu);
    const select = menu._akiOwnerSelect;
    if (select?._akiWrap && menu.parentElement !== select._akiWrap) {
      select._akiWrap.appendChild(menu);
    }
  });
  selectBackdropEl?.remove();
}

function isSelectOptionPickable(opt) {
  return !!(opt && !opt.disabled && opt.dataset.unavailable !== "1");
}

function selectCustomSelectValue(select, value, { silent = false } = {}) {
  if (!select) return false;
  const opt = [...select.options].find((o) => String(o.value) === String(value));
  if (!opt) return false;
  if (!isSelectOptionPickable(opt)) {
    if (!silent) {
      showToast("Bu secenek su an kullanilamiyor. Ayarlar > RVC veya AkiFactory.bat rvc", 4000);
    }
    return false;
  }
  select.value = value;
  if (select._akiValue) select._akiValue.textContent = opt.textContent;
  if (silent) {
    syncCustomSelect(select);
    return true;
  }
  ignoreCustomSelectDocClose = true;
  closeAllCustomSelects();
  // DOM'u tiklama ortasinda yeniden kurma — microtask'ta guncelle
  queueMicrotask(() => {
    syncCustomSelect(select);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  return true;
}

function syncCustomSelect(select) {
  const menu = select._akiMenu;
  if (!menu) return;
  menu.innerHTML = "";
  menu._akiOwnerSelect = select;
  [...select.options].filter((opt) => !opt.hidden).forEach((opt) => {
    const li = document.createElement("li");
    li.className = "aki-select-option";
    li.dataset.value = opt.value;
    li.textContent = opt.textContent;
    li.setAttribute("role", "option");
    if (!isSelectOptionPickable(opt)) li.classList.add("is-disabled");
    if (opt.selected) {
      li.classList.add("is-selected");
      li.setAttribute("aria-selected", "true");
    }
    menu.appendChild(li);
  });
  const selected = select.options[select.selectedIndex];
  if (select._akiValue) {
    select._akiValue.textContent = selected ? selected.textContent : "";
  }
}

function bindCustomSelectMenuPick(select, menu) {
  if (menu._akiPickBound) return;
  menu._akiPickBound = true;
  let lastPickAt = 0;
  let pointerDown = null;

  // pointerdown'da preventDefault YOK — aksi halde liste scroll/touch kaydirma kilitlenir.
  menu.addEventListener(
    "pointerdown",
    (e) => {
      const li = e.target.closest?.(".aki-select-option");
      if (!li || !menu.contains(li) || li.classList.contains("is-disabled")) {
        pointerDown = null;
        return;
      }
      pointerDown = { x: e.clientX, y: e.clientY, li, id: e.pointerId };
    },
    true
  );

  const commitPick = (e) => {
    if (!pointerDown) return;
    if (e.pointerId != null && pointerDown.id !== e.pointerId) return;
    const { x, y, li } = pointerDown;
    pointerDown = null;
    // Kaydirma / scroll jesti — secim yapma
    if (Math.abs(e.clientX - x) > 10 || Math.abs(e.clientY - y) > 10) return;
    if (!li || !menu.contains(li)) return;
    e.preventDefault();
    e.stopPropagation();
    if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
    const now = Date.now();
    if (now - lastPickAt < 400) return;
    lastPickAt = now;
    ignoreCustomSelectDocClose = true;
    const value = li.dataset.value;
    const opt = [...select.options].find((o) => String(o.value) === String(value));
    if (!opt || !isSelectOptionPickable(opt)) {
      showToast("Bu secenek su an kullanilamiyor. Ayarlar > RVC veya AkiFactory.bat rvc", 4000);
      closeAllCustomSelects();
      return;
    }
    selectCustomSelectValue(select, value);
  };

  menu.addEventListener("pointerup", commitPick, true);
  menu.addEventListener(
    "click",
    (e) => {
      const li = e.target.closest?.(".aki-select-option");
      if (!li || !menu.contains(li)) return;
      // pointerup zaten sectiyse tekrar etme; aksi halde click yedegi
      if (Date.now() - lastPickAt < 400) {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      pointerDown = { x: e.clientX, y: e.clientY, li, id: -1 };
      commitPick(e);
    },
    true
  );

  // Menu icinde tekerlek / trackpad scroll sayfaya ve reposition'a kacmasin
  menu.addEventListener(
    "wheel",
    (e) => {
      e.stopPropagation();
    },
    { passive: true }
  );
}

function openCustomSelect(select) {
  const wrap = select._akiWrap;
  if (!wrap) return;
  wrap.classList.add("open");
  select._akiTrigger.setAttribute("aria-expanded", "true");
  select._akiMenu.hidden = false;
  positionCustomSelectMenu(select);
  select._akiMenu.hidden = false;
}

function setupCustomSelect(select) {
  if (select.dataset.akiCustom === "1") {
    syncCustomSelect(select);
    return;
  }
  select.dataset.akiCustom = "1";
  select.classList.add("aki-select-native");
  select.tabIndex = -1;
  const wrap = document.createElement("div");
  wrap.className = "aki-select";
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "aki-select-trigger";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  trigger.innerHTML =
    '<span class="aki-select-value"></span><span class="aki-select-chevron" aria-hidden="true"></span>';
  wrap.appendChild(trigger);
  const menu = document.createElement("ul");
  menu.className = "aki-select-menu";
  menu.hidden = true;
  menu.setAttribute("role", "listbox");
  menu._akiOwnerSelect = select;
  wrap.appendChild(menu);
  select._akiWrap = wrap;
  select._akiTrigger = trigger;
  select._akiMenu = menu;
  select._akiValue = trigger.querySelector(".aki-select-value");
  bindCustomSelectMenuPick(select, menu);
  trigger.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    ignoreCustomSelectDocClose = true;
    const isOpen = wrap.classList.contains("open");
    closeAllCustomSelects();
    if (!isOpen) openCustomSelect(select);
  });
  syncCustomSelect(select);
}

function initCustomSelects(root = document) {
  const scope =
    root === document
      ? document.querySelector(".content-layer") || document
      : root;
  scope.querySelectorAll("select").forEach(setupCustomSelect);
}

function createFieldHelpButton(text) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "field-help";
  btn.setAttribute("aria-label", "Yardim");
  btn.setAttribute("tabindex", "-1");
  btn.textContent = "?";
  const tip = document.createElement("span");
  tip.className = "field-help-tip";
  tip.setAttribute("role", "tooltip");
  tip.textContent = text;
  // Tip body'de — label/select hover'i asla tetiklemesin
  tip.hidden = true;

  const hideTip = () => {
    tip.hidden = true;
    tip.classList.remove("is-visible", "align-right");
    if (tip.parentElement === document.body) {
      tip.remove();
    }
  };

  const showTip = () => {
    if (!tip.isConnected || tip.parentElement !== document.body) {
      document.body.appendChild(tip);
    }
    tip.hidden = false;
    tip.classList.add("is-visible");
    const rect = btn.getBoundingClientRect();
    const tipW = Math.min(300, window.innerWidth - 24);
    tip.style.width = "max-content";
    tip.style.maxWidth = `${tipW}px`;
    // Once yerlestir, olcup ince ayar yap
    tip.style.left = "0px";
    tip.style.top = "0px";
    const th = tip.offsetHeight || 48;
    const tw = tip.offsetWidth || tipW;
    let left = rect.left + rect.width / 2 - tw / 2;
    left = Math.max(12, Math.min(left, window.innerWidth - tw - 12));
    let top = rect.top - th - 10;
    if (top < 8) top = rect.bottom + 10;
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(top)}px`;
    tip.classList.toggle("align-right", left + tw > window.innerWidth - 20);
  };

  btn.addEventListener("mouseenter", showTip);
  btn.addEventListener("mouseleave", hideTip);
  btn.addEventListener("blur", hideTip);
  tip.addEventListener("mouseenter", hideTip);
  // Tiklama / focus ile acik kalmasin
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    hideTip();
  });
  btn.addEventListener("mousedown", (e) => {
    e.preventDefault();
    e.stopPropagation();
  });
  return btn;
}

function initFieldHelp(root = document) {
  const scope =
    root === document
      ? document.querySelector(".content-layer") || document
      : root;
  scope.querySelectorAll("[data-help]").forEach((host) => {
    if (host.dataset.helpBound === "1") return;
    const text = (host.getAttribute("data-help") || "").trim();
    if (!text) return;
    host.dataset.helpBound = "1";
    const btn = createFieldHelpButton(text);

    if (host.classList.contains("niche-actions")) {
      host.classList.add("niche-actions-with-help");
      host.appendChild(btn);
      return;
    }

    if (host.classList.contains("toggle-row")) {
      const textSpan = host.querySelector(":scope > span");
      if (textSpan) {
        const wrap = document.createElement("span");
        wrap.className = "toggle-label-wrap";
        textSpan.replaceWith(wrap);
        wrap.appendChild(textSpan);
        wrap.appendChild(btn);
      }
      return;
    }

    if (host.tagName === "DETAILS") {
      const summary = host.querySelector("summary");
      if (summary) summary.appendChild(btn);
      return;
    }

    if (host.classList.contains("block-field-label")) {
      const row = document.createElement("span");
      row.className = "field-label-row";
      const labelSpan = host.querySelector("span");
      if (labelSpan) {
        labelSpan.replaceWith(row);
        row.appendChild(labelSpan);
        row.appendChild(btn);
      }
      return;
    }

    if (host.tagName === "BUTTON") {
      const wrap = document.createElement("span");
      wrap.className = "btn-help-wrap";
      host.replaceWith(wrap);
      wrap.appendChild(host);
      wrap.appendChild(btn);
      return;
    }

    const labelSpan = host.querySelector(":scope > span");
    if (labelSpan) {
      const row = document.createElement("span");
      row.className = "field-label-row";
      labelSpan.replaceWith(row);
      row.appendChild(labelSpan);
      row.appendChild(btn);
      return;
    }

    host.appendChild(btn);
  });
}

if (!window._akiSelectRepositionBound) {
  window._akiSelectRepositionBound = true;
  window.addEventListener(
    "scroll",
    (e) => {
      // Menu kendi scroll'u — yeniden konumlama scroll'u sifirlar / kilitler.
      const t = e.target;
      if (t && t !== document && t !== document.documentElement && t !== document.body) {
        if (
          (t.classList && t.classList.contains("aki-select-menu")) ||
          (typeof t.closest === "function" && t.closest(".aki-select-menu"))
        ) {
          return;
        }
      }
      scheduleRepositionOpenSelects();
    },
    true
  );
  window.addEventListener("resize", scheduleRepositionOpenSelects);
}

function refreshAllCustomSelects() {
  document.querySelectorAll("select[data-aki-custom='1']").forEach(syncCustomSelect);
}

function ensureSelectWrapped(sel) {
  if (!sel) return;
  if (sel.dataset.akiCustom !== "1") setupCustomSelect(sel);
}

function syncSelectUi(sel) {
  if (!sel) return;
  ensureSelectWrapped(sel);
  syncCustomSelect(sel);
}

function renderTtsEngineOptions(engines, { preferred } = {}) {
  const ttsSelect = $("tts-engine");
  if (!ttsSelect || !engines?.length) return;
  const hasRvcVoices = (appConfig?.rvc_voices || []).length > 0 || !!appConfig?.rvc_available;
  const normalized = engines.map((e) => {
    if (e.id === "rvc" && hasRvcVoices) return { ...e, available: true };
    return e;
  });
  const cur = preferred || ttsSelect.value;
  ttsSelect.innerHTML = normalized
    .map((e) => {
      const unavail = !e.available;
      return `<option value="${e.id}"${unavail ? ' data-unavailable="1"' : ""}>${escapeHtml(e.label)}${unavail ? " (kurulum gerekli)" : ""}</option>`;
    })
    .join("");
  const pick =
    cur && normalized.some((e) => e.id === cur && e.available)
      ? cur
      : normalized.find((e) => e.available)?.id || cur || "edge";
  if (pick) selectCustomSelectValue(ttsSelect, pick, { silent: true });
  syncSelectUi(ttsSelect);
  updateTtsHint(normalized.find((e) => e.id === ttsSelect.value));
  updateEdgeVoiceVisibility();
  updateTtsBadge();
}

function selectShowsLoading(sel) {
  if (!sel || !sel.options.length) return false;
  const opt = sel.options[sel.selectedIndex] || sel.options[0];
  return /yukleniyor|loading/i.test(opt?.text || "");
}

function dropdownsStillLoading() {
  return ["niche", "writer-model", "editor-model", "rvc-voice", "tts-engine"].some((id) =>
    selectShowsLoading($(id))
  );
}

async function ensureDropdownsLoaded() {
  await loadConfig();
  if (dropdownsStillLoading()) {
    await new Promise((res) => setTimeout(res, 400));
    await loadConfig(true);
  }
}

document.addEventListener("click", (e) => {
  if (ignoreCustomSelectDocClose) {
    ignoreCustomSelectDocClose = false;
    return;
  }
  if (e.target.closest(".aki-select-menu, .aki-select-trigger, .aki-select-backdrop")) return;
  closeAllCustomSelects();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeAllCustomSelects();
});

function showToast(msg, ms = 2000) {
  const t = $("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.remove("hidden");
  t.classList.add("show");
  setTimeout(() => {
    t.classList.remove("show");
    t.classList.add("hidden");
  }, ms);
}

function setStartupStep(text) {
  const el = $("startup-step");
  if (el) el.textContent = text;
}

function updatePill() {
  const pill = $("api-pill");
  if (!pill) return;
  if (!engineReady) {
    if (queueActive) {
      pill.textContent = "Motor mesgul (uretim)";
      pill.className = "pill warn";
      return;
    }
    pill.textContent = "Motor baslatiliyor...";
    pill.className = "pill starting";
    return;
  }
  if (queueActive) {
    pill.textContent = "Motor mesgul (uretim)";
    pill.className = "pill warn";
    return;
  }
  pill.textContent = "Motor hazir";
  pill.className = "pill ok";
}

function applyOllamaFromHealth(oll) {
  if (!oll || typeof oll !== "object") return;
  ollamaRunning = !!oll.running;
  ollamaModelOk = oll.model_ok !== false;
  ollamaModelError = oll.model_error || "";
  updateOllamaPill();
  updateGenerateButton();
}

function applyLlmApiFromConfig(api) {
  if (!api || typeof api !== "object") return;
  if (!appConfig) appConfig = {};
  appConfig.llm_api = api;
  const writers = api.llm_writer_models || api.writer_models || [];
  if (writers.length) appConfig.llm_writer_models = writers;
  const defW = api.llm_default_writer || api.active_model || "";
  if (defW) {
    appConfig.llm_default_writer = defW;
    appConfig.llm_writer_model = defW;
  }
  updateOllamaPill();
  updateGenerateButton();
}

function isCloudLlm() {
  const p = appConfig?.llm_api?.provider || "ollama";
  return !!(p && p !== "ollama");
}

function isLlmReady() {
  if (isCloudLlm()) {
    const api = appConfig.llm_api || {};
    const p = api.provider;
    if (api.key_set === true) return true;
    return !!api[`${p}_api_key_set`];
  }
  return ollamaRunning && ollamaModelOk;
}

function llmBlockedReason() {
  if (isLlmReady()) return "";
  if (isCloudLlm()) {
    const p = appConfig?.llm_api?.provider || "bulut";
    return `${p} API anahtari yok — Ayarlar → API'ler → LLM API`;
  }
  if (!ollamaRunning) return "ollama serve komutunu calistir";
  return ollamaModelError || "LLM modeli yuklenmiyor (config.toml)";
}

function updateOllamaPill() {
  const pill = $("ollama-pill");
  if (!pill) return;
  if (!backendReachable) {
    pill.textContent = "Sunucu baglaniyor…";
    pill.className = "pill warn";
    pill.title = "Arka plan motoru yeniden baslatiliyor olabilir";
    return;
  }
  if (isCloudLlm()) {
    const api = appConfig?.llm_api || {};
    const p = api.provider || "cloud";
    const model = api.active_model || api[`${p}_model`] || "";
    if (isLlmReady()) {
      pill.textContent = `${p} hazir${model ? ` · ${model}` : ""}`;
      pill.className = "pill ok";
      pill.title = "Senaryo bulut LLM ile uretilir (Ollama gerekmez)";
      return;
    }
    pill.textContent = `${p} anahtar yok`;
    pill.className = "pill bad";
    pill.title = "Ayarlar → API'ler → LLM API";
    return;
  }
  if (!ollamaRunning) {
    pill.textContent = "Ollama kapali";
    pill.className = "pill bad";
    pill.title = "Ollama uygulamasini acin veya terminalde: ollama serve";
    return;
  }
  if (!ollamaModelOk) {
    const model = appConfig?.ollama_status?.model_name || "qwen3.5:9b";
    pill.textContent = `Model yok: ${model}`;
    pill.className = "pill warn";
    pill.title = ollamaModelError || `ollama pull ${model}`;
    return;
  }
  pill.textContent = "Ollama hazir";
  pill.className = "pill ok";
  pill.title = "";
}

function fillWriterModelSelect(writers, defWriter) {
  const writerSel = $("writer-model");
  if (!writerSel) return;
  const list = writers || [];
  const cloud = isCloudLlm();
  if (list.length) {
    writerSel.innerHTML = list
      .map((m) => {
        const avail = m.available !== false;
        const suffix = avail ? "" : cloud ? " (secilemez)" : " (ollama pull gerekli)";
        return `<option value="${escapeHtml(m.id)}" ${avail ? "" : "disabled"}>${escapeHtml(m.label || m.id)}${suffix}</option>`;
      })
      .join("");
  } else {
    writerSel.innerHTML = cloud
      ? `<option value="">Bulut model listesi bos</option>`
      : `<option value="">Yazar modeli yok (ollama pull)</option>`;
  }
  const savedWriter = localStorage.getItem(WRITER_KEY);
  const pick =
    savedWriter && list.some((m) => m.id === savedWriter && m.available !== false)
      ? savedWriter
      : defWriter && list.some((m) => m.id === defWriter && m.available !== false)
        ? defWriter
        : list.find((m) => m.available !== false)?.id || "";
  if (pick) {
    writerSel.value = pick;
    localStorage.setItem(WRITER_KEY, pick);
  }
  syncSelectUi(writerSel);
}

let _writerLiveFetched = false;

function refreshCloudWriterModels() {
  if (_writerLiveFetched || !isCloudLlm()) return;
  _writerLiveFetched = true;
  fetch("/api/settings/llm/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: appConfig.llm_api.provider }),
  })
    .then((r) => (r.ok ? readApiJson(r) : null))
    .then((d) => {
      if (!d?.writer_models?.length) return;
      appConfig.llm_writer_models = d.writer_models;
      fillWriterModelSelect(d.writer_models, currentWriterModel());
    })
    .catch(() => {});
}

function updateTtsBadge() {
  const badge = $("tts-badge");
  if (!badge) return;
  const tts = $("tts-engine")?.value || "edge";
  if (tts === "edge") {
    badge.textContent = "Bulut · Internet gerekli · Ucretsiz";
    badge.className = "tts-badge cloud";
    badge.classList.remove("hidden");
  } else if (tts === "rvc") {
    badge.textContent = "RVC · Yerel ozel ses · GPU";
    badge.className = "tts-badge local";
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

function updateGenerateButton() {
  const btn = $("btn-generate");
  if (btn) {
    const blocked = !engineReady || !isLlmReady();
    btn.disabled = blocked;
    btn.title = blocked
      ? !engineReady
        ? "Motor henuz hazir degil"
        : llmBlockedReason()
      : "";
  }
  updateLongformGenerateButton();
}

async function pollHealthStartup() {
  let attempt = 0;
  let stepIndex = 0;
  setStartupStep(STARTUP_STEPS[0]);
  const stepTimer = setInterval(() => {
    if (engineReady) return;
    stepIndex = Math.min(STARTUP_STEPS.length - 1, stepIndex + 1);
    setStartupStep(STARTUP_STEPS[stepIndex]);
  }, STEP_ADVANCE_MS);

  const tryOnce = async () => {
    attempt += 1;
    try {
      const r = await fetch("/api/health");
      const d = await readApiJson(r);
      backendReachable = true;
      if (d.ollama) applyOllamaFromHealth(d.ollama);
      if (d.llm_api) applyLlmApiFromConfig(d.llm_api);
      if (d.ok) {
        engineReady = true;
        clearInterval(stepTimer);
        setStartupStep("");
        const stepEl = $("startup-step");
        if (stepEl) stepEl.classList.add("hidden");
        showToast("✓ Motor hazir!");
        updatePill();
        updateOllamaPill();
        updateGenerateButton();
        void ensureDropdownsLoaded();
        void refreshOllamaStatus().then(() => {
          if (!isCloudLlm() && !ollamaRunning) showToast("Ollama kapali — terminalde: ollama serve", 8000);
          else if (!ollamaModelOk && ollamaModelError) showToast(ollamaModelError, 10000);
        });
        return true;
      }
    } catch {
      backendReachable = false;
      updateOllamaPill();
      /* retry */
    }
    if (attempt >= HEALTH_MAX_RETRIES) {
      clearInterval(stepTimer);
      setStartupStep(
        "Motor acilmadi — AkiFactory.bat ile yeniden baslat. (WanGP ayri uygulama; motor :8080 gerekir.)"
      );
      const pill = $("api-pill");
      if (pill) {
        pill.textContent = "Motor acilmadi";
        pill.className = "pill bad";
      }
      return true;
    }
    return false;
  };

  while (!(await tryOnce())) {
    await new Promise((res) => setTimeout(res, HEALTH_INTERVAL_MS));
  }
}

async function refreshMotorStatus() {
  try {
    const r = await fetchWithTimeout("/api/health", {}, 12000);
    const d = await readApiJson(r);
    const q = d.queue || {};
    const busy = !!(
      d.engine_busy ||
      (q.processing && (q.active_count || 0) > 0) ||
      ((q.active_count || 0) > 0 && q.worker_alive !== false) ||
      productionMode
    );
    if (suppressQueueBusyUi) {
      queueActive = false;
      if (!busy && !q.processing && !(q.active_count > 0) && !(q.pending_count > 0)) {
        suppressQueueBusyUi = false;
      }
    } else {
      queueActive = busy;
    }
    queueWorkerAlive = q.worker_alive !== false;
    if (d.ollama) applyOllamaFromHealth(d.ollama);
    if (d.ok || busy) {
      healthFailStreak = 0;
      backendReachable = true;
      if (!engineReady) {
        engineReady = true;
        setStartupStep("");
        $("startup-step")?.classList.add("hidden");
        if (!busy) showToast("✓ Motor hazir!");
      }
      updatePill();
      updateGenerateButton();
      if (dropdownsStillLoading()) void ensureDropdownsLoaded();
    } else {
      healthFailStreak += 1;
      if (healthFailStreak >= HEALTH_FAIL_BEFORE_DOWN) {
        engineReady = false;
        updatePill();
        updateGenerateButton();
      }
    }
  } catch {
    if (!queueActive) {
      healthFailStreak += 1;
      if (healthFailStreak >= HEALTH_FAIL_BEFORE_DOWN) {
        backendReachable = false;
        engineReady = false;
        updatePill();
        updateOllamaPill();
        updateGenerateButton();
      }
    }
  }
}

async function refreshOllamaStatus() {
  try {
    const r = await fetchWithTimeout("/api/health", {}, 8000);
    const d = await readApiJson(r);
    healthFailStreak = 0;
    backendReachable = true;
    if (d.ollama) {
      applyOllamaFromHealth(d.ollama);
      if (ollamaRunning && !ollamaModelOk && ollamaModelError) {
        setStatus(ollamaModelError, true);
      }
      if (appConfig) {
        appConfig.ollama_status = { ...d.ollama, configured_model: d.ollama.model_name };
      }
      updateOllamaPill();
      updateGenerateButton();
      return;
    }
    const r2 = await fetchWithTimeout("/api/ollama/status?probe=false", {}, 8000);
    const st = await readApiJson(r2);
    if (!r2.ok) throw new Error(formatApiDetail(st, `HTTP ${r2.status}`));
    applyOllamaFromHealth(st);
    if (appConfig) {
      appConfig.ollama_status = { ...st, configured_model: st.configured_model || st.model_name };
    }
  } catch {
    /* Ollama poll — backendReachable'i dusurme (gecici ag kopuklugu) */
  }
  updateOllamaPill();
  updateGenerateButton();
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.tab === name);
  });
  $("view-produce").classList.toggle("view-active", name === "produce");
  $("view-produce").hidden = name !== "produce";
  $("view-wangp").classList.toggle("view-active", name === "wangp");
  $("view-wangp").hidden = name !== "wangp";
  $("view-fooocus").classList.toggle("view-active", name === "fooocus");
  $("view-fooocus").hidden = name !== "fooocus";
  $("view-voiceconvert").classList.toggle("view-active", name === "voiceconvert");
  $("view-voiceconvert").hidden = name !== "voiceconvert";
  $("view-gallery").classList.toggle("view-active", name === "gallery");
  $("view-gallery").hidden = name !== "gallery";
  $("view-analyze").classList.toggle("view-active", name === "analyze");
  $("view-analyze").hidden = name !== "analyze";
  $("view-settings").classList.toggle("view-active", name === "settings");
  $("view-settings").hidden = name !== "settings";
  if (name === "gallery") {
    // Stats liste yanitiyla gelir; ayri istek yok
    if (galleryViewMode === "long") {
      void loadGalleryStats();
      void loadLongformGallery();
    } else {
      void loadGallery();
    }
  }
  if (name === "analyze") {
    void loadAnalyzeGalleryOptions();
    void loadAnalyzeHistory();
    initCustomSelects($("view-analyze"));
    refreshAllCustomSelects();
    populateAnalyzeVisionModels();
  }
  if (name === "voiceconvert") {
    populateVcRvcVoices();
    loadVoiceConvertHistory();
    initCustomSelects($("view-voiceconvert"));
    refreshAllCustomSelects();
  }
  if (name === "fooocus") {
    initCustomSelects($("view-fooocus"));
    refreshAllCustomSelects();
  }
  if (name === "settings") {
    const saved = localStorage.getItem(SETTINGS_SUBTAB_KEY) || "system";
    switchSettingsSubTab(saved);
    initCustomSelects($("view-settings"));
    refreshAllCustomSelects();
  }
}

function activeSettingsSubTab() {
  const active = document.querySelector(".settings-subtab.active");
  return active?.dataset.settingsTab || "system";
}

function switchSettingsSubTab(name) {
  const tab = SETTINGS_SUBTABS.includes(name) ? name : "system";
  document.querySelectorAll(".settings-subtab").forEach((btn) => {
    const on = btn.dataset.settingsTab === tab;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  SETTINGS_SUBTABS.forEach((id) => {
    const panel = $(`settings-panel-${id}`);
    if (!panel) return;
    const on = id === tab;
    panel.classList.toggle("settings-subpanel-active", on);
    panel.hidden = !on;
  });
  const hint = $("settings-head-hint");
  if (hint) hint.textContent = SETTINGS_HEAD_HINTS[tab] || "";
  $("btn-settings-refresh-all")?.classList.toggle("hidden", tab !== "files");
  localStorage.setItem(SETTINGS_SUBTAB_KEY, tab);
  void loadSettingsSubpanel(tab);
}

function activeProduceSubTab() {
  if (!$("produce-panel-long")?.hidden) return "long";
  if (!$("produce-panel-produced")?.hidden) return "produced";
  return "short";
}

function activeProduceSubject() {
  if (activeProduceSubTab() === "long") {
    return $("longform-subject")?.value?.trim() || "";
  }
  return $("subject")?.value?.trim() || "";
}

function switchProduceSubTab(name) {
  const tab = PRODUCE_SUBTABS.includes(name) ? name : "short";
  document.querySelectorAll(".produce-subtab").forEach((btn) => {
    const on = btn.dataset.produceTab === tab;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  const panels = {
    short: $("produce-panel-short"),
    long: $("produce-panel-long"),
    produced: $("produce-panel-produced"),
  };
  Object.entries(panels).forEach(([key, panel]) => {
    if (!panel) return;
    const on = key === tab;
    panel.classList.toggle("produce-subpanel-active", on);
    panel.classList.toggle("hidden", !on);
    panel.hidden = !on;
  });
  const workspace = $("produce-workspace");
  if (workspace) workspace.hidden = tab === "produced";
  if (tab === "long" && panels.long) {
    initCustomSelects(panels.long);
    refreshAllCustomSelects();
    void loadLongformDrafts();
  }
  if (tab === "produced" && panels.produced) {
    initCustomSelects(panels.produced);
    refreshAllCustomSelects();
    void loadProducedTopics();
  }
  localStorage.setItem(PRODUCE_SUBTAB_KEY, tab);
}

document.querySelectorAll(".produce-subtab").forEach((btn) => {
  btn.addEventListener("click", () => switchProduceSubTab(btn.dataset.produceTab));
});

document.querySelectorAll(".settings-subtab").forEach((btn) => {
  btn.addEventListener("click", () => switchSettingsSubTab(btn.dataset.settingsTab));
});

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

$("btn-open-gallery")?.addEventListener("click", () => switchTab("gallery"));
$("btn-refresh-gallery")?.addEventListener("click", () => {
  loadGalleryStats();
  if (galleryViewMode === "long") void loadLongformGallery();
  else void loadGallery();
});
$("gallery-tab-short")?.addEventListener("click", () => setGalleryViewMode("short"));
$("gallery-tab-long")?.addEventListener("click", () => setGalleryViewMode("long"));

function applyPlatformFromSelect() {
  const id = $("platform")?.value || "tiktok";
  const platforms = appConfig?.platforms || [];
  const p = platforms.find((x) => x.id === id);
  const customWrap = $("custom-format-wrap");
  const clipMain = $("clip-dur-main");
  const clipDurWrap = $("clip-dur-wrap");
  if (id === "custom") {
    customWrap?.classList.remove("hidden");
    clipDurWrap?.classList.remove("hidden");
  } else {
    customWrap?.classList.add("hidden");
    if (p) {
      if (clipMain) clipMain.value = p.max_clip_duration;
      const aspect = $("aspect");
      if (aspect) aspect.value = p.aspect_ratio;
      const defCount = Number(p.default_video_count) || 1;
      const countEl = $("count");
      if (countEl && !$("video-settings-accordion")?.open) countEl.value = String(defCount);
    }
  }
  updateVideoAutoSummary();
  localStorage.setItem(PLATFORM_KEY, id);
  // Platform bazli son TTS tercihini yukle
  void loadLastVoiceForPlatform(id);
  refreshAllCustomSelects();
}

function platformProfile(platformId) {
  const id = platformId || $("platform")?.value || "tiktok";
  return (appConfig?.platforms || []).find((x) => x.id === id);
}

function useManualVideoSettings() {
  return $("video-settings-accordion")?.open === true;
}

function updateVideoAutoSummary() {
  const el = $("video-auto-summary");
  if (!el) return;
  const id = $("platform")?.value || "tiktok";
  const p = platformProfile(id);
  if (!p) {
    el.textContent = "1 video · klip 5 sn (platforma gore otomatik)";
    return;
  }
  const clip = Number(p.max_clip_duration) || 5;
  const count = Number(p.default_video_count) || 1;
  const label = (p.label || id).replace(/^[^\s]+\s/, "");
  if (id === "custom") {
    const clipVal = Number($("clip-dur")?.value) || clip;
    el.textContent = `${count} video · klip ${clipVal} sn (ozel format — elle ayarlanir)`;
    return;
  }
  if (useManualVideoSettings()) {
    const manualCount = Math.min(5, Math.max(1, Number($("count")?.value) || count));
    const manualClip = Number($("clip-dur-main")?.value) || clip;
    el.textContent = `${manualCount} video · klip ${manualClip} sn (elle ayarlandi)`;
    return;
  }
  el.textContent = `${count} video · klip ${clip} sn (${label} — otomatik)`;
}

$("platform")?.addEventListener("change", applyPlatformFromSelect);

$("video-settings-accordion")?.addEventListener("toggle", updateVideoAutoSummary);
$("count")?.addEventListener("input", updateVideoAutoSummary);
$("clip-dur-main")?.addEventListener("input", updateVideoAutoSummary);
$("clip-dur")?.addEventListener("input", updateVideoAutoSummary);

function getClipDuration() {
  const platform = $("platform")?.value;
  if (platform === "custom") {
    return Number($("clip-dur")?.value) || Number($("clip-dur-main")?.value) || 5;
  }
  if (useManualVideoSettings()) {
    return Number($("clip-dur-main")?.value) || 5;
  }
  const p = platformProfile(platform);
  return Number(p?.max_clip_duration) || Number($("clip-dur-main")?.value) || 5;
}

function getVideoCount() {
  const platform = $("platform")?.value;
  const p = platformProfile(platform);
  const def = Number(p?.default_video_count) || 1;
  if (!useManualVideoSettings()) return def;
  return Math.min(5, Math.max(1, Number($("count")?.value) || def));
}

function getAspect() {
  const platform = $("platform")?.value;
  if (platform === "custom") return $("aspect")?.value || "9:16";
  const p = (appConfig?.platforms || []).find((x) => x.id === platform);
  return p?.aspect_ratio || "9:16";
}

function buildSubtitleStylePayload() {
  const styleId = $("subtitle-style")?.value || "tiktok_classic";
  const body = {
    style_id: styleId,
    subtitle_position: $("sub-position")?.value || "center",
  };
  if (styleId === "custom" || styleId === "minimal") {
    if ($("sub-font-size")?.value) body.font_size_key = $("sub-font-size").value;
    if ($("sub-color")?.value) body.text_fore_color = $("sub-color").value;
    if ($("sub-bg-box")) body.text_background_color = $("sub-bg-box").checked;
  }
  if (styleId === "custom") {
    body.font_size_key = $("sub-font-size")?.value || "medium";
    body.text_fore_color = $("sub-color")?.value || "#ffffff";
    body.text_background_color = !!$("sub-bg-box")?.checked;
  }
  return body;
}

function updateSubtitlePreview() {
  const id = $("subtitle-style")?.value || "tiktok_classic";
  const prev = $("sub-preview");
  const manual = $("subtitle-manual");
  const pos = $("sub-position")?.value || "center";
  if (prev) {
    prev.className = `sub-preview ${PREVIEW_CLASSES[id] || "sub-preview-tiktok"} sub-pos-${pos}`;
  }
  if (manual) {
    manual.classList.toggle("hidden", id !== "custom");
  }
}

$("subtitle-style")?.addEventListener("change", updateSubtitlePreview);
$("sub-color")?.addEventListener("input", updateSubtitlePreview);
$("sub-position")?.addEventListener("change", updateSubtitlePreview);

$("batch-mode")?.addEventListener("change", () => {
  const on = $("batch-mode")?.checked;
  $("single-topic-wrap")?.classList.toggle("hidden", on);
  $("batch-topics-wrap")?.classList.toggle("hidden", !on);
  $("count")?.closest("label")?.classList.toggle("hidden", on);
  if (on && !$("batch-list")?.children.length) addBatchRow();
  updateDualLanguageUi();
});

function addBatchRow(text = "") {
  const list = $("batch-list");
  if (!list || list.children.length >= 10) return;
  const li = document.createElement("li");
  li.className = "batch-row";
  li.draggable = true;
  li.innerHTML = `
    <span class="batch-drag" aria-hidden="true">⋮⋮</span>
    <input type="text" class="batch-topic-input" placeholder="Konu..." value="${escapeHtml(text)}" />
    <button type="button" class="batch-remove" title="Sil">×</button>`;
  const input = li.querySelector(".batch-topic-input");
  li.querySelector(".batch-remove")?.addEventListener("click", () => {
    li.remove();
    if (!list.children.length) addBatchRow();
  });
  li.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", "");
    li.classList.add("dragging");
  });
  li.addEventListener("dragend", () => li.classList.remove("dragging"));
  li.addEventListener("dragover", (e) => {
    e.preventDefault();
    const dragging = list.querySelector(".dragging");
    if (!dragging || dragging === li) return;
    const rect = li.getBoundingClientRect();
    const after = e.clientY > rect.top + rect.height / 2;
    list.insertBefore(dragging, after ? li.nextSibling : li);
  });
  list.appendChild(li);
  input?.focus();
}

function resetBatchTopicList() {
  const list = $("batch-list");
  if (!list) return;
  list.innerHTML = "";
  addBatchRow();
}

function syncBatchTopicRows(data) {
  const rows = [...document.querySelectorAll(".batch-row")];
  const tasks = data?.tasks || [];
  rows.forEach((row, i) => {
    const t = tasks[i];
    row.classList.toggle("batch-row-done", t?.state === 1);
    row.classList.toggle("batch-row-failed", t?.state === -1);
    row.classList.toggle("batch-row-running", t?.state === 4);
  });
}

function clearBatchTopicListIfDone(data) {
  const tasks = data?.tasks || [];
  if (!tasks.length) return;
  const allDone = tasks.every((t) => t.state === 1 || t.state === -1);
  if (!allDone || data.cancelled) return;
  if ((data.failed || 0) > 0) return;
  resetBatchTopicList();
  showToast("Konu listesi temizlendi — videolar galeride", 4000);
}

$("btn-add-topic")?.addEventListener("click", () => addBatchRow());

async function loadConfig(force = false) {
  if (loadConfigPromise && !force) return loadConfigPromise;
  loadConfigPromise = fetchAndApplyConfig().finally(() => {
    loadConfigPromise = null;
  });
  return loadConfigPromise;
}

function applyAppConfigToForm() {
  void loadAiCoverPreference();
  if (!appConfig) return;
  const langSelect = $("production-lang");
  const ttsSelect = $("tts-engine");
  const platformSelect = $("platform");
  const langs = appConfig.production_languages || [];
  if (langs.length && langSelect) {
    langSelect.innerHTML = langs
      .map((l) => `<option value="${l.id}">${escapeHtml(l.label)}</option>`)
      .join("");
  }
  const engines = appConfig.tts_engines || [];
  const platforms = appConfig.platforms || [];
  if (platformSelect && platforms.length) {
    platformSelect.innerHTML = platforms
      .map((p) => `<option value="${p.id}">${escapeHtml(p.label)}</option>`)
      .join("");
  }
  const styles = appConfig.subtitle_styles || [];
  const styleSel = $("subtitle-style");
  if (styleSel && styles.length) {
    styleSel.innerHTML = styles
      .map((s) => `<option value="${s.id}">${escapeHtml(s.label)}</option>`)
      .join("");
  }
  const sources = appConfig.video_sources || [];
  const sourceSel = $("source");
  if (sourceSel && sources.length) {
    const automaticSourceIds = new Set(["pexels", "pixabay", "pexels+pixabay"]);
    sourceSel.innerHTML = sources
      .map(
        (s) =>
          `<option value="${s.id}" ${automaticSourceIds.has(s.id) ? "" : "data-manual-only"} ${s.available ? "" : "disabled"}>${escapeHtml(s.label)}${s.available ? "" : " (key gerekli)"}</option>`
      )
      .join("");
    syncShortProductionMode();
  }
  const niches = appConfig.niches || [];
  const nicheSel = $("niche");
  if (nicheSel) {
    if (niches.length) {
      nicheSel.innerHTML = niches
        .map((n) => `<option value="${n.id}">${escapeHtml(n.label)}</option>`)
        .join("");
    } else if (selectShowsLoading(nicheSel)) {
      nicheSel.innerHTML = `<option value="tarih_gizem">Tarih ve Gizem</option><option value="genel">Genel</option>`;
    }
    syncSelectUi(nicheSel);
  }
  const galleryNicheSel = $("gallery-filter-niche");
  if (galleryNicheSel && niches.length) {
    galleryNicheSel.innerHTML =
      `<option value="">Tum nisler</option>` +
      niches.map((n) => `<option value="${n.id}">${escapeHtml(n.label)}</option>`).join("");
  }
  const wangpNicheSel = $("wangp-niche");
  if (wangpNicheSel && niches.length) {
    wangpNicheSel.innerHTML = niches
      .map((n) => `<option value="${n.id}">${escapeHtml(n.label)}</option>`)
      .join("");
  }
  const fooocusNicheSel = $("fooocus-niche");
  if (fooocusNicheSel && niches.length) {
    fooocusNicheSel.innerHTML = niches
      .map((n) => `<option value="${n.id}">${escapeHtml(n.label)}</option>`)
      .join("");
  }
  const longformNicheSel = $("longform-niche");
  if (longformNicheSel) {
    if (niches.length) {
      longformNicheSel.innerHTML = niches
        .map((n) => `<option value="${n.id}">${escapeHtml(n.label)}</option>`)
        .join("");
    } else if (selectShowsLoading(longformNicheSel)) {
      longformNicheSel.innerHTML = `<option value="tarih_gizem">Tarih ve Gizem</option><option value="genel">Genel</option>`;
    }
    syncSelectUi(longformNicheSel);
  }
  const producedNicheSel = $("produced-niche");
  if (producedNicheSel && niches.length) {
    producedNicheSel.innerHTML = niches
      .map((n) => `<option value="${n.id}">${escapeHtml(n.label)}</option>`)
      .join("");
    syncSelectUi(producedNicheSel);
  }
  const wangpStyles = appConfig.wangp_styles || [];
  const wangpStyleSel = $("wangp-style");
  if (wangpStyleSel && wangpStyles.length) {
    wangpStyleSel.innerHTML = wangpStyles
      .map((s) => `<option value="${s.id}">${escapeHtml(s.label)}</option>`)
      .join("");
  }
  const wangpModes = appConfig.wangp_line_modes || [];
  const wangpModeSel = $("wangp-line-mode");
  if (wangpModeSel && wangpModes.length) {
    wangpModeSel.innerHTML = wangpModes
      .map((m) => `<option value="${m.id}">${escapeHtml(m.label)}</option>`)
      .join("");
  }
  const fooocusStyles = appConfig.fooocus_styles || [];
  const fooocusStyleSel = $("fooocus-style");
  if (fooocusStyleSel && fooocusStyles.length) {
    fooocusStyleSel.innerHTML = fooocusStyles
      .map((s) => `<option value="${s.id}">${escapeHtml(s.label)}</option>`)
      .join("");
  }
  const fooocusPurposes = appConfig.fooocus_purposes || [];
  const fooocusPurposeSel = $("fooocus-purpose");
  if (fooocusPurposeSel && fooocusPurposes.length) {
    fooocusPurposeSel.innerHTML = fooocusPurposes
      .map((p) => `<option value="${p.id}">${escapeHtml(p.label)}</option>`)
      .join("");
  }
  if (appConfig.llm_api) applyLlmApiFromConfig(appConfig.llm_api);
  const editorSel = $("editor-model");
  const writerSel = $("writer-model");
  const editors = appConfig.llm_editor_models || [];
  const writers = appConfig.llm_writer_models || [];
  const defEditor = appConfig.llm_default_editor || "";
  const defWriter = appConfig.llm_default_writer || appConfig.llm_writer_model || "";
  fillWriterModelSelect(writers, defWriter);
  refreshCloudWriterModels();
  if (editorSel) {
    if (editors.length) {
      editorSel.innerHTML = editors
        .map(
          (m) =>
            `<option value="${escapeHtml(m.id)}" ${m.available ? "" : "disabled"}>${escapeHtml(m.label)}${m.available ? "" : " (ollama pull gerekli)"}</option>`
        )
        .join("");
    } else if (selectShowsLoading(editorSel)) {
      editorSel.innerHTML = `<option value="">Editor modeli yok (ollama pull)</option>`;
    }
    syncSelectUi(editorSel);
  }
  const savedEditor = localStorage.getItem(EDITOR_KEY);
  if (editorSel && editors.length) {
    const pick =
      savedEditor && editors.some((m) => m.id === savedEditor && m.available)
        ? savedEditor
        : defEditor && editors.some((m) => m.id === defEditor && m.available)
          ? defEditor
          : editors.find((m) => m.available)?.id || "";
    if (pick) editorSel.value = pick;
    syncSelectUi(editorSel);
  }
  const dualCb = $("dual-llm");
  const savedDual = localStorage.getItem(DUAL_LLM_KEY);
  if (dualCb) {
    dualCb.checked = savedDual === "0" ? false : appConfig.defaults?.dual_llm !== false;
  }
  const webCb = $("editor-web-verify");
  const savedWeb = localStorage.getItem(EDITOR_WEB_VERIFY_KEY);
  if (webCb) {
    webCb.checked = savedWeb === "0" ? false : appConfig.defaults?.editor_web_verify !== false;
  }
  syncEditorModelWrap();
  populateAnalyzeVisionModels();
  const savedLang = localStorage.getItem(LANG_KEY);
  const defLang = appConfig.defaults?.production_language || "tr";
  if (langSelect) {
    langSelect.value =
      savedLang && langs.some((l) => l.id === savedLang) ? savedLang : defLang;
  }
  if (ttsSelect && engines.length) {
    const savedTts = localStorage.getItem(TTS_KEY);
    const defTts = appConfig.defaults?.tts_engine || "edge";
    const pick =
      savedTts && engines.some((e) => e.id === savedTts && e.available)
        ? savedTts
        : defTts;
    renderTtsEngineOptions(engines, { preferred: pick });
  }
  populateRvcVoices();
  updateEdgeVoiceOptions();
  updateEdgeVoiceVisibility();
  const rvcFolderHint = $("rvc-folder-hint");
  if (rvcFolderHint && appConfig.rvc_folder) {
    rvcFolderHint.innerHTML =
      `Yeni ses: <code>${escapeHtml(appConfig.rvc_folder)}/SesAdi/</code> — veya <strong>Ayarlar</strong> sekmesinden kontrol et.`;
  }
  const savedPlat = localStorage.getItem(PLATFORM_KEY);
  if (platformSelect) {
    platformSelect.value =
      savedPlat && platforms.some((p) => p.id === savedPlat)
        ? savedPlat
        : appConfig.defaults?.platform || "tiktok";
  }
  const savedNiche = localStorage.getItem(NICHE_KEY);
  if (nicheSel && savedNiche) {
    nicheSel.value = savedNiche;
    syncSelectUi(nicheSel);
  }
  if (wangpNicheSel && savedNiche) wangpNicheSel.value = savedNiche;
  if (fooocusNicheSel && savedNiche) fooocusNicheSel.value = savedNiche;
  applyPlatformFromSelect();
  updateSubtitlePreview();
  updateTtsBadge();
  updateRvcRangeLabels();
  updateEdgeVoiceVisibility();
  populateBgmTracks(appConfig.bgm_tracks || []);
  populateOutros(appConfig.outros || []);
  const tagEl = document.querySelector(".tag");
  if (tagEl && appConfig.app_version) {
    tagEl.textContent = `Akiyom · Kisa video studyosu · v${appConfig.app_version}`;
  }
  const defBgmMode = appConfig.defaults?.bgm_mode || "niche";
  const bgmModeSel = $("bgm-mode");
  if (bgmModeSel) bgmModeSel.value = defBgmMode;
  const defVol = Math.round((appConfig.defaults?.bgm_volume ?? 0.2) * 100);
  const bgmVol = $("bgm-volume");
  if (bgmVol) bgmVol.value = String(defVol);
  updateBgmVolumeLabel();
  updateBgmTrackVisibility();
  const bgmHint = $("bgm-folder-hint");
  if (bgmHint && appConfig.bgm_folder) {
    bgmHint.innerHTML = `Ornek: <code>${escapeHtml(appConfig.bgm_folder)}/tarih_gizem/gerilim.mp3</code> — <strong>Ayarlar</strong> sekmesinden kontrol et.`;
  }
  updateBgmVolumeLabel();
  if (appConfig.ollama_status?.running) {
    ollamaRunning = true;
    if (appConfig.ollama_status.model_ok !== false) {
      ollamaModelOk = true;
      ollamaModelError = "";
    }
  }
  loadLastVoiceToForm();
  void syncLastVoiceFromServer();
  refreshAllCustomSelects();
  void refreshRvcVoicesFromDisk();
}

async function loadAiCoverPreference() {
  const toggle = $("auto-ai-cover");
  if (!toggle || toggle.dataset.loading === "1") return;
  toggle.dataset.loading = "1";
  try {
    const response = await fetch("/api/settings/ai-cover");
    if (!response.ok) throw new Error("Kapak ayarı yüklenemedi; uygulamayı yeniden başlat.");
    const data = await readApiJson(response);
    toggle.checked = !!data.enabled;
    if (data.installation) {
      $("ai-cover-install-status").textContent = data.installation.detail;
      $("btn-ai-cover-install").disabled = data.installation.state === "running" || data.installation.state === "done";
    }
  } catch (error) {
    $("ai-cover-setting-status").textContent = error.message;
  } finally {
    toggle.dataset.loading = "0";
  }
}

$("auto-ai-cover")?.addEventListener("change", async (event) => {
  const toggle = event.currentTarget;
  toggle.disabled = true;
  try {
    const response = await fetch("/api/settings/ai-cover", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: toggle.checked }),
    });
    if (!response.ok) throw new Error("Kapak ayarı kaydedilemedi.");
    $("ai-cover-setting-status").textContent = toggle.checked
      ? "Açık — video tamamlanınca Qwen kapak hazırlayacak."
      : "Kapalı — otomatik AI kapak üretilmeyecek.";
  } catch (error) {
    toggle.checked = !toggle.checked;
    $("ai-cover-setting-status").textContent = error.message;
  } finally { toggle.disabled = false; }
});

$("btn-ai-cover-install")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  if (!confirm("Yerel AI kapak motoru ve yaklaşık 30 GB model indirilecek. Kurulum başlasın mı?")) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/settings/ai-cover/install", { method: "POST" });
    if (!response.ok) throw new Error("Kurulum başlatılamadı.");
    const result = await readApiJson(response);
    $("ai-cover-install-status").textContent = result.detail;
    const poll = setInterval(async () => {
      await loadAiCoverPreference();
      if (!button.disabled || $("ai-cover-install-status").textContent.includes("hazir")) clearInterval(poll);
    }, 10000);
  } catch (error) {
    button.disabled = false;
    $("ai-cover-install-status").textContent = error.message;
  }
});

function applyConfigDefaults() {
  if (!appConfig) {
    appConfig = {
      niches: [
        { id: "tarih_gizem", label: "Tarih ve Gizem" },
        { id: "genel", label: "Genel" },
      ],
      tts_engines: [
        { id: "edge", label: "Edge TTS (bulut)", available: true },
        { id: "rvc", label: "RVC (ozel ses)", available: false },
      ],
      production_languages: [{ id: "tr", label: "Turkce" }],
      platforms: [
        { id: "tiktok", label: "TikTok" },
        { id: "youtube_shorts", label: "YouTube Shorts" },
        { id: "instagram_reels", label: "Instagram Reels" },
      ],
      defaults: { production_language: "tr", tts_engine: "edge", platform: "tiktok" },
      edge_voices: [],
      rvc_voices: [],
    };
  }
  applyAppConfigToForm();
}

function applyConfigFallback(reason) {
  applyConfigDefaults();
  if (reason) setStatus(reason, true);
}

async function fetchAndApplyConfig() {
  const langSelect = $("production-lang");
  const ctrl = new AbortController();
  const configTimer = setTimeout(() => ctrl.abort(), 20000);
  try {
    const r = await fetch("/api/config", { signal: ctrl.signal });
    if (!r.ok) throw new Error(`config HTTP ${r.status}`);
    appConfig = await readApiJson(r);
    applyAppConfigToForm();
  } catch (e) {
    if (e?.name === "AbortError") {
      applyConfigFallback("Ayarlar gecikti — varsayilan secenekler gosteriliyor. Sayfayi yenileyin.");
    } else if (e?.message) {
      applyConfigFallback(e.message);
    } else if (appConfig) {
      applyAppConfigToForm();
    } else {
      applyConfigFallback("Ayarlar yuklenemedi — varsayilan secenekler gosteriliyor.");
    }
    if (langSelect) {
      const saved = localStorage.getItem(LANG_KEY);
      if (saved) langSelect.value = saved;
    }
    populateRvcVoices();
  } finally {
    clearTimeout(configTimer);
    refreshAllCustomSelects();
    void refreshOllamaStatus();
  }
}

function updateEdgeVoiceOptions() {
  const lang = ($("production-lang")?.value || "tr").toLowerCase();
  const sel = $("edge-voice");
  const voices = appConfig?.edge_voices?.[lang] || appConfig?.edge_voices?.tr || [];
  if (!sel || !voices.length) return;
  const cur = sel.value;
  sel.innerHTML = voices
    .map((v) => `<option value="${escapeHtml(v.id)}">${escapeHtml(v.label)}</option>`)
    .join("");
  if (voices.some((v) => v.id === cur)) sel.value = cur;
  else {
    const def =
      voices.find((v) => String(v.id).includes("Ahmet")) ||
      voices.find((v) => String(v.id).includes("Male")) ||
      voices[0];
    if (def) sel.value = def.id;
  }
  refreshAllCustomSelects();
}

function migrateVoicePrefsToMale() {
  if (localStorage.getItem(VOICE_MALE_MIGRATE_KEY)) return;
  try {
    const raw = localStorage.getItem(LAST_VOICE_KEY);
    if (raw) {
      const lv = JSON.parse(raw);
      let changed = false;
      if (lv.edge_voice === "tr-TR-EmelNeural-Female") {
        lv.edge_voice = "tr-TR-AhmetNeural-Male";
        changed = true;
      }
      if (changed) localStorage.setItem(LAST_VOICE_KEY, JSON.stringify(lv));
    }
  } catch {
    /* ignore */
  }
  localStorage.setItem(VOICE_MALE_MIGRATE_KEY, "1");
}

function migrateEditorPrefer9b() {
  // 14B editor iyi 9B taslagi bozuyordu — kayitli tercihi bir kez sifirla
  if (localStorage.getItem(EDITOR_9B_MIGRATE_KEY)) return;
  const saved = (localStorage.getItem(EDITOR_KEY) || "").toLowerCase();
  if (saved.includes("14b") || saved === "qwen3:14b") {
    localStorage.removeItem(EDITOR_KEY);
  }
  localStorage.setItem(EDITOR_9B_MIGRATE_KEY, "1");
}

function sanitizeVoicePrefs(v) {
  if (!v || typeof v !== "object") return v;
  const out = { ...v };
  const rvc = (out.rvc_voice || "").trim();
  if (["xtts", "f5", "voxcpm", "piper", "chattts"].includes(out.tts_engine)) {
    out.tts_engine = rvc ? "rvc" : "edge";
  }
  delete out.xtts_voice;
  delete out.f5_voice;
  const pitch = Number(out.rvc_pitch);
  if (!Number.isFinite(pitch) || Math.abs(pitch) > 3) {
    out.rvc_pitch = 0;
  }
  const ir = Number(out.rvc_index_rate);
  if (!Number.isFinite(ir) || ir > 0.85) {
    out.rvc_index_rate = 0.78;
  }
  if (rvc && !out.edge_voice) {
    out.edge_voice = "tr-TR-AhmetNeural-Male";
  }
  return out;
}

function migrateVoiceRvcPipeline() {
  if (localStorage.getItem(VOICE_RVC_FIX_KEY)) return;
  try {
    const raw = localStorage.getItem(LAST_VOICE_KEY);
    if (raw) {
      const fixed = sanitizeVoicePrefs(JSON.parse(raw));
      localStorage.setItem(LAST_VOICE_KEY, JSON.stringify(fixed));
    }
  } catch {
    /* ignore */
  }
  const pitchEl = $("rvc-pitch");
  const indexEl = $("rvc-index-rate");
  if (pitchEl && Math.abs(Number(pitchEl.value || 0)) > 3) pitchEl.value = "0";
  if (indexEl && Number(indexEl.value || 1) > 0.85) indexEl.value = "0.78";
  updateRvcRangeLabels();
  localStorage.setItem(VOICE_RVC_FIX_KEY, "1");
}

function formEdgeVoice() {
  const tts = $("tts-engine")?.value || "edge";
  if (tts === "edge" || tts === "rvc") return $("edge-voice")?.value || null;
  return null;
}

function formRvcVoice() {
  const tts = $("tts-engine")?.value || "edge";
  if (tts === "rvc" || tts === "chatterbox") {
    return $("rvc-voice")?.value || null;
  }
  return null;
}

function selectedRvcVoiceMeta() {
  const id = $("rvc-voice")?.value || "";
  return (appConfig?.rvc_voices || []).find((v) => v.id === id) || null;
}

function applyRvcVoiceDefaults(voice) {
  const meta = voice || selectedRvcVoiceMeta();
  const pitch = $("rvc-pitch");
  const index = $("rvc-index-rate");
  if (pitch) pitch.value = String(meta?.pitch ?? 0);
  if (index) index.value = String(meta?.index_rate ?? 1);
  const edgeSel = $("edge-voice");
  if (edgeSel && meta?.edge_voice) {
    const opts = [...edgeSel.options].map((o) => o.value);
    if (opts.includes(meta.edge_voice)) {
      edgeSel.value = meta.edge_voice;
      syncSelectUi(edgeSel);
    } else if ((meta.gender || "").toLowerCase() === "male") {
      const ahmet = opts.find((id) => id.includes("Ahmet") || id.includes("Male"));
      if (ahmet) {
        edgeSel.value = ahmet;
        syncSelectUi(edgeSel);
      }
    }
  }
  updateRvcRangeLabels();
}

function populateRvcVoices() {
  const sel = $("rvc-voice");
  if (!sel) return;
  const voices = appConfig?.rvc_voices || [];
  if (!appConfig) {
    sel.innerHTML = `<option value="">Ses listesi yukleniyor...</option>`;
    syncSelectUi(sel);
    return;
  }
  if (!voices.length) {
    sel.innerHTML = `<option value="">RVC modeli yok — models/rvc/ klasorune .pth ekleyin</option>`;
    syncSelectUi(sel);
    return;
  }
  let preferred = sel.value || "";
  try {
    const raw = localStorage.getItem(LAST_VOICE_KEY);
    if (raw) preferred = JSON.parse(raw).rvc_voice || preferred;
  } catch {
    /* ignore */
  }
  if (!preferred) preferred = localStorage.getItem(RVC_VOICE_KEY) || "";
  sel.innerHTML = voices
    .map((v) => `<option value="${escapeHtml(v.id)}">${escapeHtml(v.label)}</option>`)
    .join("");
  const saved = preferred && voices.some((v) => v.id === preferred) ? preferred : null;
  const def = voices.find((v) => v.default) || voices[0];
  sel.value = saved || def?.id || voices[0].id;
  const chosen = voices.find((v) => v.id === sel.value);
  try {
    const lv = JSON.parse(localStorage.getItem(LAST_VOICE_KEY) || "null");
    if (lv?.rvc_voice === sel.value) {
      if ($("rvc-pitch")) $("rvc-pitch").value = String(lv.rvc_pitch ?? 0);
      if ($("rvc-index-rate")) $("rvc-index-rate").value = String(lv.rvc_index_rate ?? 1);
      updateRvcRangeLabels();
    } else {
      applyRvcVoiceDefaults(chosen);
    }
  } catch {
    applyRvcVoiceDefaults(chosen);
  }
  syncSelectUi(sel);
}

let rvcVoiceRefreshPromise = null;

async function refreshRvcVoicesFromDisk({ silent = true } = {}) {
  if (rvcVoiceRefreshPromise) return rvcVoiceRefreshPromise;
  rvcVoiceRefreshPromise = (async () => {
    try {
      const r = await fetch("/api/settings/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ section: "rvc" }),
      });
      const data = await readApiJson(r);
      if (!r.ok) throw new Error(data.detail || data.error || "RVC taramasi basarisiz");
      const prev = (appConfig?.rvc_voices || []).length;
      applySettingsRefreshData(data);
      populateRvcVoices();
      const next = (appConfig?.rvc_voices || []).length;
      if (!silent && next > prev) {
        showToast(`${next - prev} yeni RVC sesi eklendi`, 4000);
      } else if (!silent) {
        showToast(`RVC ses listesi guncellendi (${next})`, 3500);
      }
      return next;
    } finally {
      rvcVoiceRefreshPromise = null;
    }
  })();
  return rvcVoiceRefreshPromise;
}

function formVoiceRate() {
  const n = Number($("voice-rate")?.value || $("speech-rate")?.value || 1.08);
  return Number.isFinite(n) ? Math.min(1.25, Math.max(0.85, n)) : 1.08;
}

function updateVoiceRateLabel() {
  const el = $("voice-rate-val");
  const inp = $("voice-rate");
  if (el && inp) el.textContent = Number(inp.value).toFixed(2);
}

function applyRvcPresetDefault() {
  try {
    const raw = localStorage.getItem(LAST_VOICE_KEY);
    if (raw) {
      const v = sanitizeVoicePrefs(JSON.parse(raw));
      // Kullanici az once RVC secti — last_voice baska motor ise motoru geri alma
      applyVoiceToForm({ ...v, tts_engine: "rvc" });
      return;
    }
  } catch {
    /* ignore */
  }
  applyRvcVoiceDefaults();
}

/** Belgeselci ton — sadece gelismis RVC panelini acar; mevcut ayarlari degistirmez. */
function openRvcSettingsPanel() {
  const wrap = $("rvc-settings-wrap");
  if (!wrap) return;
  wrap.classList.remove("hidden");
  wrap.open = true;
  try {
    wrap.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } catch {
    /* ignore */
  }
}

function updateEdgeVoiceLabel() {
  const lbl = $("edge-voice-label");
  const lang = ($("production-lang")?.value || "tr").toLowerCase();
  const tts = $("tts-engine")?.value || "edge";
  if (!lbl) return;
  if (tts === "rvc") {
    lbl.textContent =
      lang === "en"
        ? "Edge voice (before RVC conversion)"
        : "Telaffuz sesi (RVC oncesi Edge)";
    return;
  }
  lbl.textContent =
    lang === "en" ? "Edge voice (neural)" : "Edge sesi (Turkce sinir agi)";
}

function updateEdgeVoiceVisibility() {
  const wrap = $("edge-voice-wrap");
  const rvcVoiceWrap = $("rvc-voice-wrap");
  const rvcFolderHint = $("rvc-folder-hint");
  const rvcWrap = $("rvc-settings-wrap");
  const rvcHint = $("rvc-simple-hint");
  const rvcPresetBar = $("rvc-preset-bar");
  const tts = $("tts-engine")?.value || "edge";
  const isRvc = tts === "rvc";
  const isChatterbox = tts === "chatterbox";
  const showRvcLayer = isRvc || isChatterbox;
  const showEdge = tts === "edge" || tts === "rvc";
  if (wrap) wrap.classList.toggle("hidden", !showEdge);
  if (showEdge) {
    updateEdgeVoiceLabel();
    updateEdgeVoiceOptions();
  }
  if (rvcVoiceWrap) rvcVoiceWrap.classList.toggle("hidden", !showRvcLayer);
  if (rvcFolderHint) rvcFolderHint.classList.toggle("hidden", !showRvcLayer);
  if (rvcWrap) rvcWrap.classList.toggle("hidden", !showRvcLayer);
  if (rvcPresetBar) rvcPresetBar.classList.toggle("hidden", !showRvcLayer);
  if (rvcHint) {
    rvcHint.classList.toggle("hidden", !showRvcLayer);
    if (isRvc) {
      rvcHint.textContent = "Secilen RVC sesi — varsayilan ayarlar genelde yeterli.";
    } else if (isChatterbox) {
      rvcHint.textContent =
        "Chatterbox Multilingual (TR) okur → RVC modeli. Rakamlar otomatik yaziya cevrilir.";
    }
  }
  if (showRvcLayer) {
    populateRvcVoices();
    if (isRvc) void refreshRvcVoicesFromDisk();
  }
  if (isChatterbox) applyLocalRvcIndexHint();
}

function applyLocalRvcIndexHint() {
  const idx = $("rvc-index-rate");
  if (!idx) return;
  const v = Number(idx.value);
  if (v > 0.65) {
    idx.value = "0.62";
    updateRvcRangeLabels();
  }
}

function updateRvcRangeLabels() {
  const p = $("rvc-pitch");
  const i = $("rvc-index-rate");
  const pv = $("rvc-pitch-val");
  const iv = $("rvc-index-val");
  if (p && pv) pv.textContent = p.value;
  if (i && iv) iv.textContent = Number(i.value).toFixed(2);
  updateVoiceRateLabel();
}

function updateTtsHint(engine) {
  const hint = $("tts-hint");
  if (!hint) return;
  const dual = !!$("dual-language")?.checked;
  const lang = ($("production-lang")?.value || "tr").toLowerCase();
  const tts = $("tts-engine")?.value || "edge";
  updateEdgeVoiceVisibility();
  if (dual && tts === "rvc") {
    const [l1, l2] = dualLangCodes();
    hint.textContent = ["TR", "EN"].includes(l2)
      ? `Cift dil: 1. video ${l1} RVC, 2. video ${l2} RVC. Telaffuz model ayarindan otomatik.`
      : `Cift dil: 1. video ${l1} RVC, 2. video ${l2} Edge (RVC yalnizca TR/EN).`;
    return;
  }
  if (tts === "rvc") {
    const voice = selectedRvcVoiceMeta();
    hint.textContent =
      engine?.hint ||
      (voice
        ? `${voice.label} — RVC modeli. Ton/model ayari asagida.`
        : "RVC modeli secin veya models/rvc/ klasorune .pth ekleyin.");
    return;
  }
  if (tts === "chatterbox") {
    const voice = selectedRvcVoiceMeta();
    hint.textContent =
      engine?.hint ||
      (voice
        ? `Chatterbox Multilingual → ${voice.label} RVC. Rakamlar (1940, %50) otomatik yaziya cevrilir.`
        : "Chatterbox → RVC icin asagidan model sec. Kurulum: python scripts/bootstrap.py --chatterbox");
    return;
  }
  if (engine?.hint) hint.textContent = engine.hint;
  else {
    hint.textContent = "Metin, ses ve altyazi secilen dilde uretilir.";
  }
}

function readVoiceFromForm() {
  const tts = $("tts-engine")?.value || "edge";
  const useRvc = tts === "rvc" || tts === "chatterbox";
  return {
    tts_engine: tts,
    edge_voice: tts === "edge" || tts === "rvc" ? $("edge-voice")?.value || null : null,
    rvc_voice: useRvc ? $("rvc-voice")?.value || null : null,
    rvc_pitch: Number($("rvc-pitch")?.value || 0),
    rvc_index_rate: Number($("rvc-index-rate")?.value || 1),
    voice_rate: formVoiceRate(),
  };
}

async function runVoiceTest() {
  const btn = $("btn-voice-test");
  const statusEl = $("voice-test-status");
  const audio = $("voice-test-audio");
  if (!btn) return;
  const voice = readVoiceFromForm();
  const langId = $("production-lang")?.value || "tr";
  btn.disabled = true;
  if (statusEl) statusEl.textContent = "Ses uretiliyor (~30 sn hikaye)…";
  if (audio) {
    audio.pause();
    audio.classList.add("hidden");
    audio.removeAttribute("src");
  }
  try {
    const r = await fetch("/api/voice/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...voice,
        production_language: langId,
        voice_rate: voice.voice_rate ?? formVoiceRate(),
      }),
    });
    const data = await readApiJson(r).catch(() => ({}));
    if (!r.ok) throw apiError(data, data.detail || "Ses testi basarisiz");
    const url = data.url ? `${data.url}?t=${Date.now()}` : "";
    if (!url) throw new Error("Ses URL yok");
    if (audio) {
      audio.src = url;
      audio.classList.remove("hidden");
      try {
        await audio.play();
      } catch {
        /* kullanici oynatir */
      }
    }
    const dur = data.duration_sec ? ` · ${data.duration_sec} sn` : "";
    if (statusEl) {
      statusEl.textContent = `Hazir${dur} — ${data.chain || voice.tts_engine}`;
    }
    showToast("Ses testi hazir — dinleyebilirsin", 3500);
    } catch (e) {
    const raw = e.message || "Ses testi basarisiz";
    const short =
      /torchcodec|libtorchcodec|ffmpeg/i.test(raw)
        ? "Ses motoru hatasi (torchcodec). Yeniden baslat veya Edge TTS dene."
        : raw.length > 160
          ? raw.slice(0, 159) + "…"
          : raw;
    if (statusEl) statusEl.textContent = short;
    showToast(short, 6000);
  } finally {
    btn.disabled = false;
  }
}

$("btn-voice-test")?.addEventListener("click", () => void runVoiceTest());

function voiceDisplayLabel(v, langId) {
  if (!v) return "—";
  if (v.tts_engine === "rvc") {
    const meta = (appConfig?.rvc_voices || []).find((x) => x.id === v.rvc_voice);
    return `RVC — ${meta?.label || v.rvc_voice || "secilmedi"}`;
  }
  if (v.tts_engine === "chatterbox") {
    const rvc = (appConfig?.rvc_voices || []).find((x) => x.id === v.rvc_voice);
    return rvc ? `Chatterbox → RVC — ${rvc.label}` : "Chatterbox → RVC";
  }
  const lang = (langId || $("production-lang")?.value || "tr").toLowerCase();
  const edgeList = appConfig?.edge_voices?.[lang] || [];
  const edge = edgeList.find((x) => x.id === v.edge_voice);
  return `Edge — ${edge?.label || v.edge_voice || "varsayilan"}`;
}

function refreshLastVoiceSummary() {
  const el = $("last-voice-summary");
  if (!el) return;
  el.textContent = `Son ses: ${voiceDisplayLabel(readVoiceFromForm())}`;
}

function saveLastVoiceFromForm() {
  const v = readVoiceFromForm();
  localStorage.setItem(LAST_VOICE_KEY, JSON.stringify(v));
  if (v.tts_engine) localStorage.setItem(TTS_KEY, v.tts_engine);
  if (v.rvc_voice) localStorage.setItem(RVC_VOICE_KEY, v.rvc_voice);
  refreshLastVoiceSummary();
  const platform = $("platform")?.value || localStorage.getItem(PLATFORM_KEY) || "";
  const body = { ...v };
  if (platform) body.platform = platform;
  void fetchWithTimeout(
    "/api/voice/last",
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    8000
  ).catch(() => {});
}

async function loadLastVoiceForPlatform(platformId) {
  const id = (platformId || $("platform")?.value || "").trim();
  if (!id) return;
  try {
    const r = await fetchWithTimeout(
      `/api/voice/last?platform=${encodeURIComponent(id)}`,
      {},
      8000
    );
    if (!r.ok) return;
    const data = await readApiJson(r);
    const sv = data.voice;
    if (!sv || typeof sv !== "object" || !Object.keys(sv).length) return;
    applyVoiceToForm(sv);
    localStorage.setItem(LAST_VOICE_KEY, JSON.stringify(sv));
    refreshLastVoiceSummary();
  } catch {
    /* ignore */
  }
}

async function syncLastVoiceFromServer() {
  try {
    const platform = $("platform")?.value || localStorage.getItem(PLATFORM_KEY) || "";
    const q = platform ? `?platform=${encodeURIComponent(platform)}` : "";
    const r = await fetchWithTimeout(`/api/voice/last${q}`, {}, 8000);
    if (!r.ok) return;
    const data = await readApiJson(r);
    const sv = data.voice;
    if (!sv || typeof sv !== "object" || !Object.keys(sv).length) return;
    if (!localStorage.getItem(LAST_VOICE_KEY)) {
      applyVoiceToForm(sv);
      localStorage.setItem(LAST_VOICE_KEY, JSON.stringify(sv));
      refreshLastVoiceSummary();
    }
  } catch {
    /* ignore */
  }
}

function applyVoiceToForm(v) {
  if (!v) return;
  if (v.tts_engine && $("tts-engine")) {
    const engines = appConfig?.tts_engines || [];
    if (engines.length) {
      renderTtsEngineOptions(engines, { preferred: v.tts_engine });
    } else {
      selectCustomSelectValue($("tts-engine"), v.tts_engine, { silent: true });
    }
  }
  if (v.edge_voice && $("edge-voice")) {
    $("edge-voice").value = v.edge_voice;
    syncSelectUi($("edge-voice"));
  }
  if (v.rvc_voice && $("rvc-voice")) {
    $("rvc-voice").value = v.rvc_voice;
    syncSelectUi($("rvc-voice"));
    applyRvcVoiceDefaults();
    const sp = Number(v.rvc_pitch);
    if (Number.isFinite(sp) && Math.abs(sp) <= 3) {
      if ($("rvc-pitch")) $("rvc-pitch").value = String(sp);
    }
    const si = Number(v.rvc_index_rate);
    if (Number.isFinite(si) && si <= 0.85) {
      if ($("rvc-index-rate")) $("rvc-index-rate").value = String(si);
    }
  } else {
    if ($("rvc-pitch")) $("rvc-pitch").value = String(v.rvc_pitch ?? 0);
    if ($("rvc-index-rate")) $("rvc-index-rate").value = String(v.rvc_index_rate ?? 1);
  }
  if (v.voice_rate != null && $("voice-rate")) {
    const vr = Number(v.voice_rate);
    if (Number.isFinite(vr)) $("voice-rate").value = String(vr);
  }
  updateRvcRangeLabels();
  refreshAllCustomSelects();
}

function loadLastVoiceToForm() {
  let v = null;
  try {
    const raw = localStorage.getItem(LAST_VOICE_KEY);
    if (raw) v = sanitizeVoicePrefs(JSON.parse(raw));
  } catch {
    /* ignore */
  }
  if (!v) {
    v = {
      tts_engine: localStorage.getItem(TTS_KEY) || "edge",
      rvc_voice: localStorage.getItem(RVC_VOICE_KEY) || null,
      edge_voice: $("edge-voice")?.value || null,
      rvc_pitch: Number($("rvc-pitch")?.value || 0),
      rvc_index_rate: Number($("rvc-index-rate")?.value || 1),
    };
  }
  applyVoiceToForm(v);
  refreshLastVoiceSummary();
}

function getVoiceArchiveMeta(lang) {
  const v = readVoiceFromForm();
  if (v.tts_engine === "rvc") {
    const meta = (appConfig?.rvc_voices || []).find((x) => x.id === v.rvc_voice);
    return {
      tts_provider: "rvc",
      voice: meta?.label || v.rvc_voice || "RVC",
    };
  }
  if (v.tts_engine === "chatterbox") {
    const rvc = (appConfig?.rvc_voices || []).find((x) => x.id === v.rvc_voice);
    return {
      tts_provider: "chatterbox",
      voice: rvc ? `Chatterbox → ${rvc.label}` : "Chatterbox → RVC",
    };
  }
  const edgeList = appConfig?.edge_voices?.[lang] || [];
  const edge = edgeList.find((x) => x.id === v.edge_voice);
  return {
    tts_provider: "edge",
    voice: edge?.label || v.edge_voice || "Edge",
  };
}

function defaultSecondLang(primary) {
  return primary === "en" ? "tr" : "en";
}

function populateDualSecondLang() {
  const sel = $("dual-second-lang");
  if (!sel) return;
  const primary = ($("production-lang")?.value || "tr").toLowerCase();
  const langs = (appConfig?.production_languages || [{ id: "tr" }, { id: "en" }]).filter(
    (l) => l.id !== primary
  );
  const preferred = sel.value || localStorage.getItem(DUAL_SECOND_LANG_KEY) || "";
  sel.innerHTML = langs
    .map((l) => `<option value="${escapeHtml(l.id)}">${escapeHtml(l.id.toUpperCase())} — ${escapeHtml(l.label || l.id)}</option>`)
    .join("");
  const ids = langs.map((l) => l.id);
  const fallback = defaultSecondLang(primary);
  sel.value = ids.includes(preferred) ? preferred : ids.includes(fallback) ? fallback : ids[0] || "";
  syncSelectUi(sel);
}

function dualSecondLang() {
  const primary = ($("production-lang")?.value || "tr").toLowerCase();
  const v = ($("dual-second-lang")?.value || "").toLowerCase();
  return v && v !== primary ? v : defaultSecondLang(primary);
}

function dualLangCodes() {
  const primary = ($("production-lang")?.value || "tr").toLowerCase();
  return [primary.toUpperCase(), dualSecondLang().toUpperCase()];
}

function taskLangCodes(t) {
  return [
    String(t?.primary_language || "tr").toUpperCase(),
    String(t?.second_language || "en").toUpperCase(),
  ];
}

function updateDualLanguageUi() {
  const on = !!$("dual-language")?.checked;
  const batchOn = !!$("batch-mode")?.checked;
  $("dual-language-hint")?.classList.toggle("hidden", !on);
  $("dual-second-lang-wrap")?.classList.toggle("hidden", !on);
  if (on) populateDualSecondLang();
  const hint = $("dual-language-hint");
  if (hint && on) {
    const [l1, l2] = dualLangCodes();
    hint.textContent = batchOn
      ? `Seri mod: her konu icin once ${l1}, sonra ayni gorsellerle ${l2} uretilir.`
      : `1) ${l1} video uretilir 2) Ayni stok kliplerle ${l2} versiyon otomatik uretilir.`;
  }
  updateTtsHint((appConfig?.tts_engines || []).find((e) => e.id === ($("tts-engine")?.value || "edge")));
  refreshLastVoiceSummary();
}

function saveLanguagePref() {
  const v = $("production-lang")?.value;
  if (v) localStorage.setItem(LANG_KEY, v);
}

function saveTtsPref() {
  const v = $("tts-engine")?.value;
  if (v) localStorage.setItem(TTS_KEY, v);
}

$("production-lang")?.addEventListener("change", () => {
  saveLanguagePref();
  if ($("dual-language")?.checked) updateDualLanguageUi();
  updateEdgeVoiceOptions();
  updateEdgeVoiceLabel();
  refreshLastVoiceSummary();
  fetch("/api/config")
    .then((r) => readApiJson(r))
    .then((cfg) => {
      const id = $("tts-engine")?.value;
      updateTtsHint((cfg.tts_engines || []).find((e) => e.id === id));
    })
    .catch(() => updateTtsHint(null));
});
$("niche")?.addEventListener("change", () => {
  const v = $("niche")?.value;
  if (v) localStorage.setItem(NICHE_KEY, v);
  populateBgmTracks(appConfig?.bgm_tracks || []);
  updateBgmNicheHint();
  void loadTopicMemoryHint();
  void loadProducedTopics();
});

$("btn-produced-refresh")?.addEventListener("click", () => void loadProducedTopics());
$("produced-niche")?.addEventListener("change", () => void loadProducedTopics());

$("rvc-pitch")?.addEventListener("input", () => {
  updateRvcRangeLabels();
  saveLastVoiceFromForm();
});
$("rvc-index-rate")?.addEventListener("input", () => {
  updateRvcRangeLabels();
  saveLastVoiceFromForm();
});
$("btn-rvc-preset-default")?.addEventListener("click", applyRvcPresetDefault);
$("btn-rvc-preset-documentary")?.addEventListener("click", openRvcSettingsPanel);
$("voice-rate")?.addEventListener("input", () => {
  updateVoiceRateLabel();
  saveLastVoiceFromForm();
});
$("rvc-voice")?.addEventListener("change", () => {
  applyRvcVoiceDefaults();
  saveLastVoiceFromForm();
  updateTtsHint((appConfig?.tts_engines || []).find((e) => e.id === "rvc"));
});
$("edge-voice")?.addEventListener("change", () => saveLastVoiceFromForm());

$("bgm-mode")?.addEventListener("change", updateBgmTrackVisibility);
$("outro")?.addEventListener("change", () => {
  const v = $("outro")?.value || "";
  if (v) localStorage.setItem(OUTRO_KEY, v);
  else localStorage.removeItem(OUTRO_KEY);
  updateOutroHint();
});
$("bgm-track")?.addEventListener("change", () => {
  const audio = $("bgm-preview-audio");
  if (audio) audio.pause();
});
$("btn-bgm-preview")?.addEventListener("click", playBgmPreview);
$("bgm-volume")?.addEventListener("input", updateBgmVolumeLabel);

$("tts-engine")?.addEventListener("change", () => {
  saveTtsPref();
  const tts = $("tts-engine")?.value || "edge";
  if (tts === "rvc") applyRvcPresetDefault();
  if (tts === "chatterbox") applyLocalRvcIndexHint();
  updateEdgeVoiceVisibility();
  updateTtsBadge();
  saveLastVoiceFromForm();
  fetch("/api/config")
    .then((r) => readApiJson(r))
    .then((cfg) => {
      const id = $("tts-engine")?.value;
      updateTtsHint((cfg.tts_engines || []).find((e) => e.id === id));
    })
    .catch(() => updateTtsHint(null));
});

/** FastAPI hata govdesi: detail string, dizi veya obje olabilir */
function formatApiDetail(data, fallback = "Islem basarisiz") {
  if (!data) return fallback;
  const d = data.detail ?? data.message ?? data.error ?? data;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const loc = Array.isArray(item.loc) ? item.loc.filter((x) => x !== "body").join(".") : "";
          const msg = item.msg || item.message || "";
          return loc ? `${loc}: ${msg}` : msg;
        }
        return String(item);
      })
      .filter(Boolean)
      .join(" · ") || fallback;
  }
  if (d && typeof d === "object") {
    return d.message || d.msg || JSON.stringify(d);
  }
  return fallback;
}

function apiError(data, fallback) {
  return new Error(formatApiDetail(data, fallback));
}

async function fetchWithTimeout(url, options = {}, ms = 20000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...options, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

/** Sunucu JSON yerine duz metin (Internal Server Error vb.) dondururse anlamli hata verir */
async function readApiJson(r) {
  const text = await r.text();
  if (!text.trim()) return {};
  try {
    return JSON.parse(text);
  } catch {
    const snippet = text.trim().replace(/\s+/g, " ").slice(0, 180);
    throw new Error(`Sunucu JSON yerine metin dondurdu (HTTP ${r.status}): ${snippet}`);
  }
}

async function fetchApi(url, options = {}, fallback = "Islem basarisiz") {
  const r = await fetch(url, options);
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, fallback);
  return data;
}

/** LLM/Ollama VRAM bosalt — is bitince veya pencere kapanirken */
function releaseLlmResources() {
  fetch("/api/ollama/unload", { method: "POST", keepalive: true }).catch(() => {});
}

function setStatus(msg, isErr = false) {
  const el = $("status-msg");
  if (!el) return;
  const text =
    typeof msg === "string" ? msg : msg && typeof msg === "object" ? formatApiDetail(msg) : String(msg ?? "");
  el.textContent = text;
  el.classList.toggle("err", isErr);
}

function showProgress(pct, label) {
  $("progress-wrap")?.classList.remove("hidden");
  const fill = $("progress-fill");
  if (fill) fill.style.width = `${pct}%`;
  const text = $("progress-text");
  if (text) text.textContent = label || `${pct}%`;
}

function hideProgress() {
  $("progress-wrap")?.classList.add("hidden");
}

const PIPELINE_PANELS = {
  short: {
    wrap: "pipeline-wrap",
    title: "pipeline-title",
    sublabel: "pipeline-sublabel",
    steps: "pipeline-steps",
  },
  long: {
    wrap: "longform-pipeline-wrap",
    title: "longform-pipeline-title",
    sublabel: "longform-pipeline-sublabel",
    steps: "longform-pipeline-steps",
  },
};

const PIPELINE_PRESETS = {
  topicSuggest: [
    { id: "analyze", label: "Nis analizi" },
    { id: "generate", label: "Konular uretiliyor" },
    { id: "done", label: "Tamamlandi" },
  ],
  scriptSimple: [
    { id: "write", label: "Senaryo yaziliyor" },
    { id: "done", label: "Tamamlandi" },
  ],
  scriptDual: [
    { id: "writer", label: "Yazar LLM taslak yaziyor" },
    { id: "editor", label: "Editor modeli duzenliyor" },
    { id: "done", label: "Tamamlandi" },
  ],
  videoEngine: [
    { id: "script", label: "Senaryo" },
    { id: "terms", label: "Anahtar kelime" },
    { id: "tts", label: "Ses (TTS)" },
    { id: "video", label: "Goruntu / stok klip" },
    { id: "subs", label: "Altyazi" },
    { id: "montage", label: "Montaj" },
    { id: "publish", label: "Yayin paketi" },
    { id: "done", label: "Tamamlandi" },
  ],
  longformPlan: [
    { id: "analyze", label: "Ana konu analizi" },
    { id: "chapters", label: "Bolumler planlaniyor" },
    { id: "done", label: "Plan hazir" },
  ],
  longformProduce: [
    { id: "script", label: "Senaryo" },
    { id: "tts", label: "Ses + altyazi" },
    { id: "materials", label: "Gorseller" },
    { id: "done", label: "Tamamlandi" },
  ],
};

const ENGINE_STEP_BY_NAME = {
  Senaryo: 0,
  "Anahtar kelime": 1,
  TTS: 2,
  Goruntu: 3,
  Altyazi: 4,
  Montaj: 5,
};

const pipelineRuntime = { short: null, long: null };

function pipelineEls(panel) {
  const cfg = PIPELINE_PANELS[panel] || PIPELINE_PANELS.short;
  return {
    wrap: $(cfg.wrap),
    title: $(cfg.title),
    sublabel: $(cfg.sublabel),
    steps: $(cfg.steps),
  };
}

function engineStepIndexFromTask(pct, stepName) {
  if (stepName && ENGINE_STEP_BY_NAME[stepName] !== undefined) {
    return ENGINE_STEP_BY_NAME[stepName];
  }
  const p = Number(pct) || 0;
  if (p < 10) return 0;
  if (p < 20) return 1;
  if (p < 30) return 2;
  if (p < 40) return 3;
  if (p < 50) return 4;
  if (p < 100) return 5;
  return 6;
}

function renderPipeline(panel) {
  const state = pipelineRuntime[panel];
  const { wrap, title, sublabel, steps } = pipelineEls(panel);
  if (!wrap || !steps || !state) return;

  wrap.classList.remove("hidden", "is-done", "is-error", "is-running");
  if (state.status === "done") wrap.classList.add("is-done");
  else if (state.status === "error") wrap.classList.add("is-error");
  else wrap.classList.add("is-running");

  if (title) title.textContent = state.title || "Uretim";
  if (sublabel) sublabel.textContent = state.sublabel || "";

  const active = state.activeIndex ?? 0;

  steps.innerHTML = state.steps
    .map((step, i) => {
      let cls = "is-pending";
      if (state.status === "error" && i === active) cls = "is-error";
      else if (state.status === "done") cls = "is-done";
      else if (i < active) cls = "is-done";
      else if (i === active) cls = "is-active";

      const badge =
        cls === "is-active"
          ? `<span class="pipeline-step-badge">Simdi</span>`
          : cls === "is-done"
            ? `<span class="pipeline-step-badge">OK</span>`
            : cls === "is-error"
              ? `<span class="pipeline-step-badge">Hata</span>`
              : "";

      const dots =
        cls === "is-active"
          ? `<span class="pipeline-step-dots" aria-hidden="true"><span></span><span></span><span></span></span>`
          : "";

      return `<li class="pipeline-step ${cls}" data-step="${escapeHtml(step.id)}">
        <span class="pipeline-step-dot" aria-hidden="true"></span>
        <span class="pipeline-step-label">${escapeHtml(step.label)}${dots}</span>
        ${badge}
      </li>`;
    })
    .join("");
}

function startPipeline(panel, presetKey, title, sublabel = "") {
  const preset = PIPELINE_PRESETS[presetKey];
  if (!preset) return;
  pipelineRuntime[panel] = {
    presetKey,
    steps: preset.map((s) => ({ ...s })),
    title: title || "Uretim",
    sublabel,
    activeIndex: 0,
    status: "running",
  };
  renderPipeline(panel);
}

function setPipelineStep(panel, index, sublabel = "") {
  const state = pipelineRuntime[panel];
  if (!state) return;
  state.activeIndex = Math.max(0, Math.min(index, state.steps.length - 1));
  if (sublabel) state.sublabel = sublabel;
  state.status = "running";
  renderPipeline(panel);
}

function updatePipelineFromEngine(panel, pct, stepName, sublabelPrefix = "") {
  const state = pipelineRuntime[panel];
  if (!state || state.presetKey !== "videoEngine") return;
  const idx = engineStepIndexFromTask(pct, stepName);
  const label = stepName || state.steps[idx]?.label || "";
  const pctNum = Math.min(100, Number(pct) || 0);
  const sub = sublabelPrefix
    ? `${sublabelPrefix} — ${label} ${pctNum}%`
    : `${label} ${pctNum}%`;
  setPipelineStep(panel, idx, sub);
}

function completePipeline(panel, sublabel = "Uretim tamamlandi") {
  const state = pipelineRuntime[panel];
  if (!state) return;
  state.status = "done";
  state.activeIndex = state.steps.length - 1;
  state.sublabel = sublabel;
  renderPipeline(panel);
}

function failPipeline(panel, sublabel = "Uretim basarisiz") {
  const state = pipelineRuntime[panel];
  if (!state) return;
  state.status = "error";
  state.sublabel = sublabel;
  renderPipeline(panel);
}

function hidePipeline(panel) {
  pipelineRuntime[panel] = null;
  const { wrap } = pipelineEls(panel);
  wrap?.classList.add("hidden");
  wrap?.classList.remove("is-done", "is-error", "is-running");
}

function updateProductionStopUi() {
  const active = !!productionMode || queueActive;
  const onLong = activeProduceSubTab() === "long";
  $("production-stop-row")?.classList.toggle("hidden", !active || onLong);
  $("longform-production-stop-row")?.classList.toggle("hidden", !active || !onLong);
  document.querySelectorAll(".btn-stop-production").forEach((btn) => {
    btn.disabled = stopProductionInFlight;
  });
}

function queueNotificationTarget() {
  return activeProduceSubTab() === "long" ? $("queue-notifications-long") : $("queue-notifications");
}

function clearQueueNotifications() {
  for (const id of ["queue-notifications", "queue-notifications-long"]) {
    const el = $(id);
    if (el) el.innerHTML = "";
  }
}

function pushQueueNotification(msg, kind = "info") {
  const el = queueNotificationTarget();
  if (!el || !msg) return;
  const p = document.createElement("p");
  p.className = `queue-notif${kind === "warn" ? " warn" : kind === "error" ? " error" : ""}`;
  p.textContent = msg;
  el.prepend(p);
  while (el.children.length > 10) el.lastChild?.remove();
}

function focusOutputJob(refId, kind) {
  outputFocusRefId = refId || null;
  outputFocusKind = kind || null;
  if (kind === "longform") {
    startPipeline("long", "longformProduce", "Uretim", "Kuyruk — basliyor");
  } else if (refId) {
    startPipeline("short", "videoEngine", "Uretim", "Kuyruk — basliyor");
  }
}

function isOutputFocusedRef(refId) {
  return !!outputFocusRefId && outputFocusRefId === refId;
}

function shouldDriveOutputPipeline(current) {
  if (!current?.ref_id) return !!productionMode;
  if (!outputFocusRefId) return !!productionMode;
  return current.ref_id === outputFocusRefId;
}

function syncQueueActiveFromSnapshot(q) {
  if (suppressQueueBusyUi || stopProductionInFlight || productionCancelled) {
    queueActive = false;
    return;
  }
  const active = (q?.active_count || 0) > 0;
  queueActive = !!(
    (q?.processing && active) ||
    (active && q?.worker_alive !== false)
  );
}

function updateOutputQueueWaitHint(q) {
  if (!productionMode || !outputFocusRefId) return;
  const current = q?.current;
  if (current?.ref_id === outputFocusRefId) return;
  const mine = (q?.items || []).find((it) => it.ref_id === outputFocusRefId);
  if (!mine || mine.status === "done" || mine.status === "failed") return;
  const pos = mine.position || "?";
  const panel = mine.kind === "longform" ? "long" : "short";
  if (panel === "long") {
    setPipelineStep("long", 0, `Kuyruk — ${pos}. sira (baska is bitene kadar bekleniyor)`);
  } else {
    setPipelineStep("short", 0, `Kuyruk — ${pos}. sira (baska is bitene kadar bekleniyor)`);
  }
}

function productionQueueListEls() {
  return [$("production-queue-list"), $("production-queue-list-long")].filter(Boolean);
}

function beginProduction(mode) {
  productionMode = mode;
  queueCompletionNotified = false;
  productionCancelled = false;
  stopProductionInFlight = false;
  suppressQueueBusyUi = false;
  generateAbortController = new AbortController();
  currentTaskId = null;
  currentDualTaskId = null;
  finalizedQueueJobs.clear();
  updateProductionStopUi();
}

function endProduction() {
  productionMode = null;
  productionCancelled = false;
  stopProductionInFlight = false;
  generateAbortController = null;
  currentTaskId = null;
  currentDualTaskId = null;
  outputFocusRefId = null;
  outputFocusKind = null;
  updateProductionStopUi();
}

function isProductionCancelled() {
  return productionCancelled;
}

async function stopProduction() {
  if (stopProductionInFlight || (!productionMode && !queueActive)) return;
  stopProductionInFlight = true;
  productionCancelled = true;
  suppressQueueBusyUi = true;
  queueActive = false;
  updateProductionStopUi();
  updatePill();
  clearQueueNotifications();
  pushQueueNotification("Durduruluyor…", "warn");

  generateAbortController?.abort();

  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  if (longformPollTimer) {
    clearInterval(longformPollTimer);
    longformPollTimer = null;
  }
  if (queuePollTimer) {
    clearInterval(queuePollTimer);
    queuePollTimer = null;
  }

  const withTimeout = (promise, ms = 6000) =>
    Promise.race([
      promise,
      new Promise((resolve) => setTimeout(() => resolve({ timedOut: true }), ms)),
    ]);

  try {
    const deletes = [fetch("/api/queue", { method: "DELETE" })];
    if (currentTaskId) {
      deletes.push(fetch(`/api/tasks/${encodeURIComponent(currentTaskId)}`, { method: "DELETE" }));
    }
    if (currentDualTaskId) {
      deletes.push(fetch(`/api/tasks/${encodeURIComponent(currentDualTaskId)}`, { method: "DELETE" }));
    }
    if (currentBatchId) {
      deletes.push(fetch(`/api/batch/${currentBatchId}`, { method: "DELETE" }));
    }
    if (currentLongformId) {
      deletes.push(fetch(`/api/longform/${currentLongformId}`, { method: "DELETE" }));
    }
    await withTimeout(Promise.allSettled(deletes), 6000);
  } catch {
    /* ignore — UI yine de durdurulmus gosterilecek */
  }

  queueActive = false;
  currentBatchId = null;
  currentLongformId = null;
  currentTaskId = null;
  currentDualTaskId = null;
  queuePollLastCurrent = null;
  renderProductionQueue({
    items: [],
    processing: false,
    active_count: 0,
    pending_count: 0,
    worker_alive: true,
  });

  const mode = productionMode;
  if (mode === "longform" || outputFocusKind === "longform") {
    failPipeline("long", "Uretim durduruldu");
    setLongformStatus("Uretim durduruldu.");
  } else if (mode || outputFocusRefId) {
    failPipeline("short", "Uretim durduruldu");
    setStatus("Uretim durduruldu.");
  }

  hideProgress();
  $("batch-progress-wrap")?.classList.add("hidden");
  $("longform-progress-wrap")?.classList.add("hidden");
  updateGenerateButton();
  updateLongformGenerateButton();
  $("btn-generate").disabled = !engineReady || !isLlmReady();
  releaseLlmResources();
  endProduction();
  clearQueueNotifications();
  pushQueueNotification("Uretim durduruldu — sira temizlendi", "warn");
  showToast("Uretim durduruldu", 3000);
  stopProductionInFlight = false;
  updatePill();
  updateProductionStopUi();
}

function videoFilenameFromSubject(subject) {
  const s = (subject || "akifactory")
    .replace(/[<>:"/\\|?*]+/g, "")
    .trim()
    .slice(0, 80);
  const base = s || "akifactory";
  return base.toLowerCase().endsWith(".mp4") ? base : `${base}.mp4`;
}

function applyPreviewChrome() {
  const toolbar = $("preview-toolbar");
  if (toolbar) toolbar.classList.toggle("hidden", !currentVideoUrl);
  document.querySelector(".out-panel")?.classList.toggle("preview-panel-expanded", previewExpanded);
  const box = $("preview");
  if (box) {
    box.classList.toggle("preview-scroll", previewZoom > 1 || previewExpanded);
  }
  const resetBtn = $("btn-preview-zoom-reset");
  if (resetBtn) resetBtn.textContent = `${Math.round(previewZoom * 100)}%`;
  $("btn-preview-expand")?.classList.toggle("hidden", previewExpanded);
  $("btn-preview-shrink")?.classList.toggle("hidden", !previewExpanded);
}

function renderPreview() {
  const box = $("preview");
  if (!box || !currentVideoUrl) return;
  box.classList.remove("empty");
  box.innerHTML = "";
  const stage = document.createElement("div");
  stage.className = previewExpanded ? "preview-stage is-expanded" : "preview-stage";
  stage.style.transform = `scale(${previewZoom})`;
  const video = document.createElement("video");
  video.controls = true;
  video.autoplay = previewAutoplay;
  video.playsInline = true;
  video.src = currentVideoUrl;
  stage.appendChild(video);
  box.appendChild(stage);
  applyPreviewChrome();
}

function resetPreviewView() {
  previewZoom = 1;
  previewExpanded = false;
  if (currentVideoUrl) renderPreview();
  else applyPreviewChrome();
}

function setPreviewZoom(next) {
  previewZoom = Math.min(PREVIEW_ZOOM_MAX, Math.max(PREVIEW_ZOOM_MIN, next));
  renderPreview();
}

function showVideo(url, suggestedName = "akifactory.mp4", productionSec = 0, { autoplay = true, label = "" } = {}) {
  currentVideoUrl = url || "";
  currentVideoName = suggestedName || "akifactory.mp4";
  previewAutoplay = autoplay;
  previewZoom = 1;
  previewExpanded = false;
  renderPreview();
  updatePreviewOutputMeta(productionSec, label);
  $("btn-download")?.classList.remove("hidden");
  $("btn-open-gallery")?.classList.remove("hidden");
}

async function showGalleryItemInOutput(entryId, { autoplay = true } = {}) {
  if (!entryId) return false;
  try {
    const r = await fetch(`/api/gallery/${encodeURIComponent(entryId)}`);
    if (!r.ok) return false;
    const item = await readApiJson(r);
    const url = item?.stream_url || `/api/gallery/${encodeURIComponent(entryId)}/stream`;
    outputGalleryId = item?.id || entryId;
    showVideo(url, videoFilenameFromSubject(item?.subject), item?.production_sec || 0, {
      autoplay,
      label: galleryTitleText(item || {}),
    });
    const pack = item?.publish_pack;
    if (pack && (pack.titles?.length || pack.descriptions?.length || pack.best_title)) {
      renderPublishPack(pack);
    } else {
      clearPublishPack();
    }
    return true;
  } catch {
    return false;
  }
}

/** Cikti bos veya eski videoyu gosteriyorsa galerideki en son kisa videoyu goster. */
async function showLatestOutput({ autoplay = false } = {}) {
  if (productionMode && outputFocusRefId) return;
  const shownBefore = outputGalleryId;
  try {
    const r = await fetch("/api/gallery");
    if (!r.ok) return;
    const data = await readApiJson(r);
    const latest = (data.items || [])[0];
    if (!latest?.id || latest.id === outputGalleryId) return;
    if (outputGalleryId !== shownBefore || (productionMode && outputFocusRefId)) return;
    await showGalleryItemInOutput(latest.id, { autoplay });
  } catch {
    /* sessiz */
  }
}

function showArchivedInOutput(archived, focused) {
  const entry = (archived?.items || []).slice(-1)[0];
  if (!entry?.id) return;
  if (!focused && productionMode && outputFocusRefId) return;
  void showGalleryItemInOutput(entry.id, { autoplay: true });
}

function clearPreview() {
  currentVideoUrl = "";
  currentVideoName = "akifactory.mp4";
  outputGalleryId = null;
  lastPublishPack = null;
  previewZoom = 1;
  previewExpanded = false;
  const box = $("preview");
  if (box) {
    box.classList.add("empty");
    box.classList.remove("preview-scroll");
    box.innerHTML = "<p>Henuz video yok.</p>";
  }
  applyPreviewChrome();
  $("btn-download")?.classList.add("hidden");
  $("btn-open-gallery")?.classList.add("hidden");
  updatePreviewOutputMeta(0);
  clearPublishPack();
}

function clearPublishPack() {
  $("publish-pack")?.classList.add("hidden");
  const lists = ["publish-titles", "publish-descriptions", "publish-hashtags", "publish-share-tips"];
  lists.forEach((id) => {
    const el = $(id);
    if (el) el.innerHTML = "";
  });
  const st = $("publish-pack-status");
  if (st) st.textContent = "";
  const meta = $("publish-pack-meta");
  if (meta) meta.textContent = "";
  $("publish-wangp-wrap")?.classList.add("hidden");
  const wp = $("publish-wangp-prompt");
  const wn = $("publish-wangp-negative");
  if (wp) wp.value = "";
  if (wn) wn.value = "";
}

function publishTitleGlowClass(rank) {
  const r = Number(rank);
  if (r === 1) return " publish-title-glow-1";
  if (r === 2) return " publish-title-glow-2";
  if (r === 3) return " publish-title-glow-3";
  return " publish-title-glow-n";
}

function parseTagsFromRaw(raw) {
  if (!raw) return [];
  const s = String(raw).trim();
  const tags = [];
  const seen = new Set();
  const add = (part) => {
    const t = String(part).trim().replace(/^#+/, "").trim();
    if (!t) return;
    const key = t.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    tags.push(t);
  };
  if (s.includes(",")) {
    s.split(",").forEach(add);
  } else {
    s.split(/[\s\n]+/).forEach(add);
  }
  return tags;
}

const YOUTUBE_TAG_SUFFIXES = ["enigma", "atlas"];

function formatYoutubeTags(raw) {
  const tags = parseTagsFromRaw(raw);
  const suffixKeys = new Set(YOUTUBE_TAG_SUFFIXES.map((s) => s.toLowerCase()));
  const out = tags.filter((t) => !suffixKeys.has(t.toLowerCase()));
  for (const s of YOUTUBE_TAG_SUFFIXES) out.push(s);
  return out.join(", ");
}

function collectYoutubeTagsFromPack(pack, item = null) {
  const parts = [];
  if (pack?.youtube_tags) parts.push(pack.youtube_tags);
  (pack?.hashtag_sets || []).forEach((h) => parts.push(h.text));
  if (pack?.best_hashtags) parts.push(pack.best_hashtags);
  if (item?.hashtags) parts.push(item.hashtags);
  return formatYoutubeTags(parts.join(" "));
}

function renderYoutubeTagsBlock(tagsText, { why = "", showHint = true } = {}) {
  const tags = parseTagsFromRaw(tagsText);
  if (!tags.length) {
    return '<p class="publish-empty">Uretilemedi.</p>';
  }
  const pills = tags
    .map((t) => `<span class="youtube-tag-pill">${escapeHtml(t)}</span>`)
    .join("");
  const whyHtml = why ? `<p class="publish-why">${escapeHtml(why)}</p>` : "";
  const hint = showHint
    ? '<p class="hint youtube-tags-hint">YouTube Studio → Etiketler alanina yapistirin (virgulle ayrilir).</p>'
    : "";
  return `<div class="youtube-tags-block">
    <div class="youtube-tags-preview" aria-label="YouTube etiketleri">${pills}</div>
    ${whyHtml}
    ${hint}
    <div class="gallery-detail-btn-col gallery-detail-btn-col-inline">
      <button type="button" class="btn-ghost btn-sm btn-copy-youtube-tags">YouTube etiketlerini kopyala</button>
      <button type="button" class="btn-ghost btn-sm btn-gallery-field-regen" data-regen-field="tags">Degistir</button>
    </div>
  </div>`;
}

function bindYoutubeTagsCopy(root, tagsText) {
  const btn = root?.querySelector?.(".btn-copy-youtube-tags");
  if (!btn) return;
  btn.addEventListener("click", () => {
    copyText(formatYoutubeTags(tagsText), btn);
  });
}

function renderPublishList(containerId, items, textKey = "text") {
  const el = $(containerId);
  if (!el) return;
  if (!items?.length) {
    el.innerHTML = '<li class="publish-empty">Uretilemedi.</li>';
    return;
  }
  const isTitles = containerId === "publish-titles";
  el.innerHTML = items
    .map((item, idx) => {
      const rank = item.rank ?? item.order ?? idx + 1;
      const why = item.why ? `<span class="publish-why">${escapeHtml(item.why)}</span>` : "";
      const textCls = isTitles
        ? `publish-text publish-title-text${publishTitleGlowClass(rank)}`
        : "publish-text";
      return `<li class="publish-item">
        <div class="publish-item-row">
          <span class="publish-rank">${rank}</span>
          <p class="${textCls}">${escapeHtml(item[textKey] || "")}</p>
          <button type="button" class="btn-ghost btn-sm btn-copy-inline" data-copy-idx="${idx}">Kopyala</button>
        </div>
        ${why}
      </li>`;
    })
    .join("");
  el.querySelectorAll(".btn-copy-inline").forEach((btn) => {
    const idx = Number(btn.dataset.copyIdx);
    const text = items[idx]?.[textKey] || "";
    btn.addEventListener("click", () => copyText(text, btn));
  });
}

function renderPublishAlternatives(elId, alts, prefix = "A/B alternatif") {
  const el = $(elId);
  if (!el) return;
  if (!alts?.length) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.classList.remove("hidden");
  el.textContent = `${prefix}: ${alts.map((a) => a.text).join(" · ")}`;
}

function renderPublishPack(data) {
  lastPublishPack = data;
  $("publish-pack")?.classList.remove("hidden");
  const meta = $("publish-pack-meta");
  if (meta) {
    meta.textContent = `Editor: ${data.editor_model || "—"} · Yazar: ${data.writer_model || appConfig?.llm_writer_model || "—"}`;
  }
  renderPublishList("publish-titles", data.titles);
  renderPublishList("publish-descriptions", data.descriptions);
  renderPublishAlternatives("publish-title-alts", data.title_alternatives);
  renderPublishAlternatives("publish-caption-alts", data.caption_alternatives, "A/B aciklama");
  const tagsEl = $("publish-hashtags");
  const youtubeTags = collectYoutubeTagsFromPack(data);
  const tagWhy = data.hashtag_sets?.[0]?.why || "";
  if (tagsEl) {
    tagsEl.innerHTML = renderYoutubeTagsBlock(youtubeTags, { why: tagWhy });
    bindYoutubeTagsCopy(tagsEl, youtubeTags);
  }
  const tipsEl = $("publish-share-tips");
  if (tipsEl) {
    const tips = data.share_tips || [];
    if (!tips.length) {
      tipsEl.innerHTML = '<li class="publish-empty">Oneri uretilemedi.</li>';
    } else {
      tipsEl.innerHTML = tips
        .map(
          (t) => `<li class="publish-tip">
            <span class="publish-rank">${t.order}</span>
            <div>
              ${t.category ? `<span class="hint publish-tip-cat">${escapeHtml(t.category)}</span>` : ""}
              <strong>${escapeHtml((t.tip || "").trim() || (t.detail || "").trim())}</strong>
              ${(() => {
                const main = (t.tip || "").trim() || (t.detail || "").trim();
                const det = (t.detail || "").trim();
                return det && det !== main ? `<p class="hint">${escapeHtml(det)}</p>` : "";
              })()}
            </div>
          </li>`
        )
        .join("");
    }
  }
  const wangp = data.wangp;
  const wWrap = $("publish-wangp-wrap");
  if (wangp?.prompt_block && wWrap) {
    wWrap.classList.remove("hidden");
    const wp = $("publish-wangp-prompt");
    const wn = $("publish-wangp-negative");
    if (wp) wp.value = wangp.prompt_block;
    if (wn) wn.value = wangp.negative_prompt || "";
  } else {
    wWrap?.classList.add("hidden");
  }
  const st = $("publish-pack-status");
  if (st) st.textContent = "Yayin paketi hazir — secilen baslik, aciklama ve YouTube etiketleri.";
}

let producedTopicsCache = [];

async function loadProducedTopics() {
  const list = $("produced-list");
  if (!list) return;
  const niche = $("produced-niche")?.value || $("niche")?.value || "tarih_gizem";
  try {
    const r = await fetch(`/api/topic-memory?niche=${encodeURIComponent(niche)}`);
    if (!r.ok) throw new Error("yuklenemedi");
    const data = await readApiJson(r);
    const items = Array.isArray(data.produced_items) && data.produced_items.length
      ? data.produced_items
      : (data.produced || []).map((title) => ({ id: null, title }));
    producedTopicsCache = items.map((it) => it.title || it);
    if (!items.length) {
      list.innerHTML = '<li class="history-empty">Bu niste henuz uretim yok.</li>';
      return;
    }
    list.innerHTML = items
      .map((it, i) => {
        const title = it.title || it;
        const idxLabel =
          it.id != null ? `${i + 1}. (#${it.id})` : `${i + 1}.`;
        return `
      <li class="history-item produced-item">
        <button type="button" class="history-fill" data-produced-fill="${i}" title="Konu kutusuna yaz">
          <span class="produced-index">${escapeHtml(String(idxLabel))}</span>
          <span class="history-topic">${escapeHtml(title)}</span>
        </button>
        <button type="button" class="history-delete danger btn-sm" data-produced-del="${i}" title="Sil — tekrar uretilebilir">Sil</button>
      </li>`;
      })
      .join("");

    list.querySelectorAll("[data-produced-fill]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const topic = producedTopicsCache[Number(btn.dataset.producedFill)];
        if (!topic) return;
        if ($("subject")) $("subject").value = topic;
        if ($("longform-subject")) $("longform-subject").value = topic;
        switchProduceSubTab("short");
        $("subject")?.focus();
        showToast("Konu kısa video kutusuna yazıldı", 2500);
      });
    });

    list.querySelectorAll("[data-produced-del]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const topic = producedTopicsCache[Number(btn.dataset.producedDel)];
        if (!topic) return;
        const url = `/api/topic-memory?niche=${encodeURIComponent(niche)}&topic=${encodeURIComponent(topic)}`;
        const res = await fetch(url, { method: "DELETE" });
        if (!res.ok) {
          setStatus("Silinemedi", true);
          return;
        }
        showToast("Uretilenlerden silindi — bu konu tekrar uretilebilir", 3500);
        void loadProducedTopics();
        void loadTopicMemoryHint();
      });
    });
  } catch {
    list.innerHTML = '<li class="history-empty">Uretilenler yuklenemedi.</li>';
  }
}

async function loadTopicMemoryHint() {
  const el = $("topic-memory-hint");
  if (!el) return;
  const niche = $("niche")?.value || "tarih_gizem";
  try {
    const r = await fetch(`/api/topic-memory?niche=${encodeURIComponent(niche)}`);
    if (!r.ok) return;
    const data = await readApiJson(r);
    const n = data?.stats?.produced ?? 0;
    if (n > 0) {
      el.classList.remove("hidden");
      el.textContent = `Bu niste ${n} konu daha once uretildi — oneriler tekrar etmez.`;
    } else {
      el.classList.add("hidden");
      el.textContent = "";
    }
  } catch {
    el.classList.add("hidden");
  }
}

async function loadPublishReview(subject, script, aspect, langOverride = null, opts = {}) {
  if (!script || script.trim().length < 10) {
    if (!opts.silent) {
      $("publish-pack")?.classList.remove("hidden");
      const st = $("publish-pack-status");
      if (st) st.textContent = "Senaryo bulunamadi — yayin paketi atlandi.";
    }
    return null;
  }
  const prodLang = langOverride || $("production-lang")?.value || "tr";
  const st = $("publish-pack-status");
  if (!opts.silent) {
    $("publish-pack")?.classList.remove("hidden");
    if (st) st.textContent = "Editor LLM yayin paketini hazirliyor (baslik, hashtag, oneri)…";
  }
  try {
    const clipDur = getClipDuration();
    const sceneCount = Math.min(8, Math.max(3, Math.round(clipDur) || 5));
    const r = await fetch("/api/publish/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic: subject,
        script: script.trim(),
        platform: opts.platform || $("platform")?.value || "tiktok",
        production_language: prodLang,
        niche: opts.niche || $("niche")?.value || "genel",
        editor_model: currentEditorModel() || null,
        video_aspect: aspect || getAspect(),
        include_wangp: false,
        include_fooocus: true,
        include_share_tips: prodLang === "tr",
        scene_count: sceneCount,
        wangp_style: "dark_mystery",
        wangp_line_mode: "sliding_window",
      }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Yayin paketi uretilemedi");
    if (!opts.silent) renderPublishPack(data);
    else lastPublishPack = data;
    return data;
  } catch (e) {
    if (!opts.silent && st) {
      st.textContent = e.message;
      st.classList.add("error");
    }
    return null;
  } finally {
    releaseLlmResources();
  }
}

async function saveVideoFile(url, filename) {
  const name = filename || "akifactory.mp4";
  const target = url || currentVideoUrl;
  if (!target) {
    setStatus("Kaydedilecek video yok.", true);
    return;
  }
  try {
    if (window.akifactory?.saveVideo) {
      const r = await window.akifactory.saveVideo(target, name);
      if (r?.cancelled) return;
      if (r?.ok) {
        showToast(`Kaydedildi: ${r.path || name}`);
        return;
      }
      throw new Error(r?.error || "Kayit basarisiz");
    }
    if (window.pywebview?.api?.save_video) {
      const r = await window.pywebview.api.save_video(target, name);
      if (r?.cancelled) return;
      if (r?.ok) {
        showToast(`Kaydedildi: ${r.path || name}`);
        return;
      }
      throw new Error(r?.error || "Kayit basarisiz");
    }
    if (window.showSaveFilePicker) {
      const handle = await window.showSaveFilePicker({
        suggestedName: name,
        types: [{ description: "MP4 Video", accept: { "video/mp4": [".mp4"] } }],
      });
      const res = await fetch(target);
      if (!res.ok) throw new Error("Video indirilemedi");
      const blob = await res.blob();
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      showToast("Video kaydedildi");
      return;
    }
    const a = document.createElement("a");
    a.href = target;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast("Indirme basladi (tarayici indirme klasoru)");
  } catch (e) {
    if (e?.name === "AbortError") return;
    setStatus(e.message || "Kayit basarisiz", true);
  }
}

function syncEditorModelWrap() {
  const on = !!$("dual-llm")?.checked;
  const follows = appConfig?.llm_editor_follows_writer !== false;
  // Ayrı editor kapali: select her zaman gizli; web dogrulama dual acikken gorunur
  $("editor-model-field")?.classList.toggle("hidden", follows || !on);
  $("editor-web-verify-wrap")?.classList.toggle("hidden", !on);
}

$("dual-llm")?.addEventListener("change", () => {
  localStorage.setItem(DUAL_LLM_KEY, $("dual-llm")?.checked ? "1" : "0");
  syncEditorModelWrap();
});

$("editor-web-verify")?.addEventListener("change", () => {
  localStorage.setItem(EDITOR_WEB_VERIFY_KEY, $("editor-web-verify")?.checked ? "1" : "0");
});

$("writer-model")?.addEventListener("change", () => {
  const v = $("writer-model")?.value;
  if (v) localStorage.setItem(WRITER_KEY, v);
  if (v && isCloudLlm()) {
    const provider = appConfig?.llm_api?.provider || "";
    const body = { provider };
    if (provider === "gemini") body.gemini_model = v;
    else if (provider === "openai") body.openai_model = v;
    else if (provider === "nvidia") body.nvidia_model = v;
    else if (provider === "grok") body.grok_model = v;
    else if (provider === "claude") body.claude_model = v;
    fetch("/api/settings/llm", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then((r) => (r.ok ? readApiJson(r) : null))
      .then((d) => {
        if (d) applyLlmApiFromConfig(d);
      })
      .catch(() => {});
  }
});

$("editor-model")?.addEventListener("change", () => {
  const v = $("editor-model")?.value;
  if (v) localStorage.setItem(EDITOR_KEY, v);
});

function currentWriterModel() {
  return $("writer-model")?.value || appConfig?.llm_default_writer || appConfig?.llm_writer_model || "";
}

function currentEditorModel() {
  // Ayrı editor yok — dogrulama da yazar modeliyle
  if (appConfig?.llm_editor_follows_writer !== false) {
    return currentWriterModel();
  }
  return $("editor-model")?.value || appConfig?.llm_default_editor || "";
}

function currentScriptForGenerate() {
  return (
    pendingScript ||
    $("script-preview-text")?.value?.trim() ||
    ""
  );
}

function syncScriptFromEditor() {
  const ta = $("script-preview-text");
  const text = (ta?.value || pendingScript || "").trim();
  if (ta && text && !ta.value.trim()) ta.value = text;
  pendingScript = text;
  return text;
}

function buildGenerateBody(subject) {
  const styleId = $("subtitle-style")?.value || "tiktok_classic";
  const tts = $("tts-engine")?.value || "edge";
  const script = syncScriptFromEditor();
  return {
    video_subject: subject,
    platform: $("platform")?.value || "tiktok",
    video_aspect: getAspect(),
    video_source: $("source")?.value || "pexels",
    production_language: $("production-lang")?.value || "tr",
    tts_engine: tts,
    tts_provider: tts,
    niche: $("niche")?.value || "genel",
    strengthen_hook: !!$("strengthen-hook")?.checked,
    dual_llm: !script && !!($("dual-llm")?.checked),
    editor_web_verify: !!($("editor-web-verify")?.checked),
    writer_model: currentWriterModel() || null,
    editor_model: currentEditorModel() || null,
    video_script: script || null,
    edge_voice: formEdgeVoice(),
    rvc_voice: formRvcVoice(),
    rvc_pitch: Number($("rvc-pitch")?.value || 0),
    rvc_index_rate: Number($("rvc-index-rate")?.value || 1),
    voice_rate: formVoiceRate(),
    video_clip_duration: getClipDuration(),
    video_count: getVideoCount(),
    subtitle_enabled: styleId !== "off",
    subtitle_style: buildSubtitleStylePayload(),
    bgm_mode: $("bgm-mode")?.value || "niche",
    bgm_track: $("bgm-track")?.value || null,
    bgm_volume: Number($("bgm-volume")?.value || 20) / 100,
    outro_id: ($("outro")?.value || "").trim() || null,
    use_lang_preset: false,
    ai_manual_visuals: false,
    production_mode: $("production-mode-manual")?.checked ? "manual" : "automatic",
  };
}

function collectDraftState() {
  const script =
    pendingScript ||
    $("script-preview-text")?.value?.trim() ||
    "";
  return {
    batch_mode: !!$("batch-mode")?.checked,
    subject: $("subject")?.value?.trim() || "",
    batch_topics: getBatchTopics(),
    platform: $("platform")?.value || "tiktok",
    video_source: $("source")?.value || "pexels",
    production_mode: $("production-mode-manual")?.checked ? "manual" : "automatic",
    video_aspect: $("aspect")?.value || getAspect(),
    clip_dur: Number($("clip-dur")?.value) || 5,
    clip_dur_main: Number($("clip-dur-main")?.value) || 5,
    video_count: Number($("count")?.value) || 1,
    video_settings_manual: useManualVideoSettings(),
    production_language: $("production-lang")?.value || "tr",
    tts_engine: $("tts-engine")?.value || "edge",
    edge_voice: $("edge-voice")?.value || null,
    rvc_voice: $("rvc-voice")?.value || null,
    rvc_pitch: Number($("rvc-pitch")?.value || 0),
    rvc_index_rate: Number($("rvc-index-rate")?.value || 1),
    niche: $("niche")?.value || "genel",
    strengthen_hook: !!$("strengthen-hook")?.checked,
    dual_llm: !script && !!($("dual-llm")?.checked),
    editor_web_verify: !!($("editor-web-verify")?.checked),
    writer_model: currentWriterModel() || null,
    editor_model: currentEditorModel() || null,
    video_script: script,
    subtitle_style: buildSubtitleStylePayload(),
    bgm_mode: $("bgm-mode")?.value || "niche",
    bgm_track: $("bgm-track")?.value || null,
    bgm_volume: Number($("bgm-volume")?.value || 20) / 100,
    outro_id: ($("outro")?.value || "").trim() || null,
  };
}

function applySubtitleStyleFromDraft(st) {
  if (!st) return;
  const styleId = st.style_id || "tiktok_classic";
  if ($("subtitle-style")) $("subtitle-style").value = styleId;
  if (st.font_size_key && $("sub-font-size")) $("sub-font-size").value = st.font_size_key;
  if (st.text_fore_color && $("sub-color")) $("sub-color").value = st.text_fore_color;
  if (st.subtitle_position && $("sub-position")) $("sub-position").value = st.subtitle_position;
  if ($("sub-bg-box") && st.text_background_color != null) {
    $("sub-bg-box").checked = !!st.text_background_color;
  }
  updateSubtitlePreview();
}

function applyDraftState(s) {
  if (!s) return;
  const batchOn = !!s.batch_mode;
  if ($("batch-mode")) $("batch-mode").checked = batchOn;
  $("single-topic-wrap")?.classList.toggle("hidden", batchOn);
  $("batch-topics-wrap")?.classList.toggle("hidden", !batchOn);
  $("count")?.closest("label")?.classList.toggle("hidden", batchOn);
  const list = $("batch-list");
  if (list) {
    list.innerHTML = "";
    if (batchOn) {
      const topics = s.batch_topics?.length ? s.batch_topics : [""];
      topics.forEach((t) => addBatchRow(t));
    }
  }
  if (!batchOn && $("subject")) $("subject").value = s.subject || "";

  if ($("niche")) $("niche").value = s.niche || "genel";
  if ($("platform")) $("platform").value = s.platform || "tiktok";
  if ($("source")) $("source").value = s.video_source || "pexels";
  if ($("production-mode-manual")) {
    $("production-mode-manual").checked = s.production_mode === "manual";
    syncShortProductionMode();
  }
  if ($("aspect")) $("aspect").value = s.video_aspect || "9:16";
  if ($("clip-dur")) $("clip-dur").value = String(s.clip_dur ?? 5);
  if ($("clip-dur-main")) $("clip-dur-main").value = String(s.clip_dur_main ?? 5);
  if ($("count")) $("count").value = String(s.video_count ?? 1);
  const acc = $("video-settings-accordion");
  if (acc) acc.open = !!s.video_settings_manual;

  if ($("production-lang")) $("production-lang").value = s.production_language || "tr";
  updateEdgeVoiceOptions();
  if ($("tts-engine")) $("tts-engine").value = s.tts_engine || "edge";
  if (s.edge_voice && $("edge-voice")) $("edge-voice").value = s.edge_voice;
  if (s.rvc_voice && $("rvc-voice")) $("rvc-voice").value = s.rvc_voice;
  if ($("rvc-pitch")) $("rvc-pitch").value = String(s.rvc_pitch ?? 0);
  if ($("rvc-index-rate")) $("rvc-index-rate").value = String(s.rvc_index_rate ?? 1);
  updateRvcRangeLabels();

  if ($("strengthen-hook")) $("strengthen-hook").checked = s.strengthen_hook !== false;
  if ($("dual-llm")) $("dual-llm").checked = s.dual_llm !== false;
  if ($("editor-web-verify")) $("editor-web-verify").checked = s.editor_web_verify !== false;
  syncEditorModelWrap();
  if (s.writer_model && $("writer-model")) $("writer-model").value = s.writer_model;
  if (s.editor_model && $("editor-model")) $("editor-model").value = s.editor_model;

  applySubtitleStyleFromDraft(s.subtitle_style);

  if ($("bgm-mode")) $("bgm-mode").value = s.bgm_mode || "niche";
  if ($("bgm-track") && s.bgm_track) $("bgm-track").value = s.bgm_track;
  if ($("bgm-volume")) {
    $("bgm-volume").value = String(Math.round((s.bgm_volume ?? 0.2) * 100));
    updateBgmVolumeLabel();
  }
  if ($("outro")) $("outro").value = s.outro_id || "";

  applyPlatformFromSelect();
  if (s.video_settings_manual) {
    if ($("clip-dur-main")) $("clip-dur-main").value = String(s.clip_dur_main ?? 5);
    if ($("count")) $("count").value = String(s.video_count ?? 1);
  }
  if (s.platform === "custom" && $("clip-dur")) {
    $("clip-dur").value = String(s.clip_dur ?? 5);
  }

  pendingScript = s.video_script || "";
  const ta = $("script-preview-text");
  if (ta) ta.value = pendingScript;
  updateScriptMetaFromText(pendingScript);

  updateBgmTrackVisibility();
  updateEdgeVoiceVisibility();
  updateTtsHint();
  updateOutroHint();
  updateVideoAutoSummary();
  refreshAllCustomSelects();
}

function updateDraftStatus(label) {
  const el = $("draft-status");
  if (!el) return;
  if (currentDraftId && label) {
    el.textContent = `Yuklu taslak: ${label} — "Taslağı kaydet" ile guncellenir.`;
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

function draftMetaLine(s) {
  const parts = [];
  if (s.platform) parts.push(s.platform);
  if (s.niche) parts.push(s.niche);
  if (s.video_script) parts.push("senaryo var");
  return parts.join(" · ");
}

async function loadDrafts() {
  const list = $("drafts-list");
  if (!list) return;
  try {
    const r = await fetch("/api/drafts");
    const data = await readApiJson(r);
    const items = (data.items || []).filter((d) => d.settings?.mode !== "longform");
    if (!items.length) {
      list.innerHTML = '<li class="history-empty">Henuz taslak yok.</li>';
      return;
    }
    list.innerHTML = items
      .map((d) => {
        const s = d.settings || {};
        const meta = draftMetaLine(s);
        const updated = d.updated_at ? new Date(d.updated_at).toLocaleString("tr-TR") : "";
        const active = d.id === currentDraftId ? " is-active" : "";
        return `
      <li class="draft-item history-item${active}" data-id="${escapeHtml(d.id)}">
        <button type="button" class="history-fill draft-load" data-load="${escapeHtml(d.id)}">
          <span class="history-topic">${escapeHtml(d.label || s.subject || "Taslak")}</span>
          <span class="history-meta">${escapeHtml(meta)}${updated ? ` · ${escapeHtml(updated)}` : ""}</span>
        </button>
        <button type="button" class="draft-produce" data-produce="${escapeHtml(d.id)}" title="Yukle ve uret">▶</button>
        <button type="button" class="draft-delete" data-del="${escapeHtml(d.id)}" title="Sil">×</button>
      </li>`;
      })
      .join("");

    const byId = Object.fromEntries(items.map((d) => [d.id, d]));

    list.querySelectorAll("[data-load]").forEach((btn) => {
      btn.addEventListener("click", () => applyDraftFromList(btn.dataset.load, byId, false));
    });
    list.querySelectorAll("[data-produce]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        applyDraftFromList(btn.dataset.produce, byId, true);
      });
    });
    list.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm("Taslak silinsin mi?")) return;
        await fetch(`/api/drafts/${btn.dataset.del}`, { method: "DELETE" });
        if (currentDraftId === btn.dataset.del) {
          currentDraftId = null;
          updateDraftStatus("");
        }
        loadDrafts();
      });
    });
  } catch {
    list.innerHTML = '<li class="history-empty">Taslaklar yuklenemedi.</li>';
  }
}

function applyDraftFromList(id, byId, andGenerate) {
  const d = byId[id];
  if (!d?.settings) return;
  applyDraftState(d.settings);
  currentDraftId = d.id;
  updateDraftStatus(d.label || d.settings.subject || "Taslak");
  loadDrafts();
  showToast(andGenerate ? "Taslak yuklendi — uretim basliyor" : "Taslak yuklendi");
  $("view-produce")?.scrollIntoView({ behavior: "smooth", block: "start" });
  if (andGenerate) onGenerate();
}

async function saveCurrentDraft() {
  const settings = collectDraftState();
  if (!settings.batch_mode && (!settings.subject || settings.subject.length < 2)) {
    setStatus("Taslak icin once konu yazin (en az 2 karakter).", true);
    return;
  }
  if (settings.batch_mode && !settings.batch_topics.length) {
    setStatus("Seri modda en az bir konu ekleyin.", true);
    return;
  }
  const defaultLabel = settings.batch_mode
    ? settings.batch_topics[0]
    : settings.subject;
  let existing = null;
  if (currentDraftId) {
    try {
      const list = await fetch("/api/drafts").then((r) => readApiJson(r));
      existing = (list.items || []).find((d) => d.id === currentDraftId);
    } catch {
      existing = null;
    }
  }
  const manualLabel = ($("draft-label")?.value || "").trim();
  const label =
    manualLabel ||
    existing?.label ||
    (defaultLabel || "Taslak").slice(0, 80);

  try {
    const res = await fetch("/api/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: currentDraftId,
        label,
        settings,
      }),
    });
    const data = await readApiJson(res);
    if (!res.ok) throw apiError(data, "Taslak kaydedilemedi");
    currentDraftId = data.id;
    if ($("draft-label")) $("draft-label").value = data.label || label;
    updateDraftStatus(data.label);
    showToast(`Taslak kaydedildi: ${data.label}`);
    loadDrafts();
  } catch (e) {
    setStatus(e.message || "Taslak kaydedilemedi", true);
  }
}

function collectLongformDraftState() {
  return {
    mode: "longform",
    longform_subject: $("longform-subject")?.value?.trim() || "",
    longform_chapters: longformChapters.map(normalizeLongformChapter),
    longform_niche: $("longform-niche")?.value || "tarih_gizem",
    longform_platform: $("longform-platform")?.value || "youtube",
    longform_aspect: getLongformAspect(),
    longform_dual_language: !!$("longform-dual-language")?.checked,
    longform_source: $("longform-source")?.value || "pexels",
    longform_auto_retry: $("longform-auto-retry")?.checked !== false,
  };
}

function applyLongformDraftState(s) {
  if (!s) return;
  if ($("longform-subject")) {
    $("longform-subject").value = s.longform_subject || s.subject || "";
  }
  if ($("longform-niche")) $("longform-niche").value = s.longform_niche || s.niche || "tarih_gizem";
  if ($("longform-platform")) {
    $("longform-platform").value = s.longform_platform || s.platform || "youtube";
  }
  if ($("longform-aspect")) {
    const a = s.longform_aspect || s.video_aspect;
    if (a === "16:9" || a === "9:16" || a === "1:1") {
      $("longform-aspect").value = a;
    } else {
      syncLongformAspectFromPlatform();
    }
  }
  updateLongformAspectHint();
  if ($("longform-dual-language")) {
    $("longform-dual-language").checked = !!s.longform_dual_language;
  }
  $("longform-dual-hint")?.classList.toggle("hidden", !$("longform-dual-language")?.checked);
  if ($("longform-source")) $("longform-source").value = s.longform_source || "pexels";
  if ($("longform-auto-retry")) {
    $("longform-auto-retry").checked = s.longform_auto_retry !== false;
  }
  longformChapters = (s.longform_chapters || []).map((ch) => normalizeLongformChapter(ch));
  renderLongformChapters();
  refreshAllCustomSelects();
}

function updateLongformDraftStatus(label) {
  const el = $("longform-draft-status");
  if (!el) return;
  if (currentLongformDraftId && label) {
    el.textContent = `Yuklu taslak: ${label} — "Taslağı kaydet" ile guncellenir.`;
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

function longformDraftMetaLine(s) {
  const parts = ["uzun video"];
  if (s.longform_niche || s.niche) parts.push(s.longform_niche || s.niche);
  const chapters = s.longform_chapters || [];
  if (chapters.length) parts.push(`${chapters.length} bolum`);
  const withScript = chapters.filter((c) => (c.script || "").trim()).length;
  if (withScript) parts.push(`${withScript} senaryo`);
  if (s.longform_dual_language) parts.push("TR+EN");
  return parts.join(" · ");
}

async function loadLongformDrafts() {
  const list = $("longform-drafts-list");
  if (!list) return;
  try {
    const r = await fetch("/api/drafts");
    const data = await readApiJson(r);
    const items = (data.items || []).filter((d) => d.settings?.mode === "longform");
    if (!items.length) {
      list.innerHTML = '<li class="history-empty">Henuz taslak yok.</li>';
      return;
    }
    list.innerHTML = items
      .map((d) => {
        const s = d.settings || {};
        const meta = longformDraftMetaLine(s);
        const updated = d.updated_at ? new Date(d.updated_at).toLocaleString("tr-TR") : "";
        const active = d.id === currentLongformDraftId ? " is-active" : "";
        return `
      <li class="draft-item history-item${active}" data-id="${escapeHtml(d.id)}">
        <button type="button" class="history-fill draft-load" data-load="${escapeHtml(d.id)}">
          <span class="history-topic">${escapeHtml(d.label || s.longform_subject || s.subject || "Uzun video")}</span>
          <span class="history-meta">${escapeHtml(meta)}${updated ? ` · ${escapeHtml(updated)}` : ""}</span>
        </button>
        <button type="button" class="draft-produce" data-produce="${escapeHtml(d.id)}" title="Yukle ve uret">▶</button>
        <button type="button" class="draft-delete" data-del="${escapeHtml(d.id)}" title="Sil">×</button>
      </li>`;
      })
      .join("");

    const byId = Object.fromEntries(items.map((d) => [d.id, d]));

    list.querySelectorAll("[data-load]").forEach((btn) => {
      btn.addEventListener("click", () => applyLongformDraftFromList(btn.dataset.load, byId, false));
    });
    list.querySelectorAll("[data-produce]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        applyLongformDraftFromList(btn.dataset.produce, byId, true);
      });
    });
    list.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm("Taslak silinsin mi?")) return;
        await fetch(`/api/drafts/${btn.dataset.del}`, { method: "DELETE" });
        if (currentLongformDraftId === btn.dataset.del) {
          currentLongformDraftId = null;
          updateLongformDraftStatus("");
        }
        loadLongformDrafts();
      });
    });
  } catch {
    list.innerHTML = '<li class="history-empty">Taslaklar yuklenemedi.</li>';
  }
}

function applyLongformDraftFromList(id, byId, andGenerate) {
  const d = byId[id];
  if (!d?.settings) return;
  switchProduceSubTab("long");
  applyLongformDraftState(d.settings);
  currentLongformDraftId = d.id;
  if ($("longform-draft-label")) $("longform-draft-label").value = d.label || "";
  updateLongformDraftStatus(d.label || d.settings.longform_subject || "Taslak");
  loadLongformDrafts();
  showToast(andGenerate ? "Taslak yuklendi — uretim basliyor" : "Taslak yuklendi");
  $("produce-panel-long")?.scrollIntoView({ behavior: "smooth", block: "start" });
  if (andGenerate) void onLongformGenerate();
}

async function saveLongformDraft() {
  const settings = collectLongformDraftState();
  if (!settings.longform_subject || settings.longform_subject.length < 2) {
    setLongformStatus("Taslak icin ana konu yazin (en az 2 karakter).", true);
    return;
  }
  const defaultLabel = settings.longform_subject;
  let existing = null;
  if (currentLongformDraftId) {
    try {
      const list = await fetch("/api/drafts").then((r) => readApiJson(r));
      existing = (list.items || []).find((d) => d.id === currentLongformDraftId);
    } catch {
      existing = null;
    }
  }
  const manualLabel = ($("longform-draft-label")?.value || "").trim();
  const label =
    manualLabel ||
    existing?.label ||
    `${defaultLabel.slice(0, 50)} (${settings.longform_chapters?.length || 0} bolum)`.slice(0, 80);

  try {
    const res = await fetch("/api/drafts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: currentLongformDraftId,
        label,
        settings,
      }),
    });
    const data = await readApiJson(res);
    if (!res.ok) throw apiError(data, "Taslak kaydedilemedi");
    currentLongformDraftId = data.id;
    if ($("longform-draft-label")) $("longform-draft-label").value = data.label || label;
    updateLongformDraftStatus(data.label);
    showToast(`Taslak kaydedildi: ${data.label}`);
    await loadLongformDrafts();
    $("longform-drafts-list")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    setLongformStatus("");
  } catch (e) {
    setLongformStatus(e.message || "Taslak kaydedilemedi", true);
  }
}

function populateOutros(list) {
  const sel = $("outro");
  if (!sel) return;
  const cur = localStorage.getItem(OUTRO_KEY) || sel.value || "";
  const items = list || [];
  sel.innerHTML =
    '<option value="">Intro / outro yok</option>' +
    items
      .map((o) => {
        const parts = [o.intro_file ? "intro" : "", o.file ? "outro" : ""].filter(Boolean).join(" + ");
        return `<option value="${escapeHtml(o.id)}">${escapeHtml(o.label)} · ${parts}</option>`;
      })
      .join("");
  if (cur && items.some((o) => o.id === cur)) sel.value = cur;
  refreshAllCustomSelects();
  updateOutroHint();
}

function updateOutroHint() {
  const hint = $("outro-hint");
  const sel = $("outro");
  if (!hint || !sel) return;
  const folder = appConfig?.outros_folder || "data/outros";
  const id = sel.value;
  if (!id) {
    hint.innerHTML = `Kanal intro / outro eklemek icin: <strong>Ayarlar → Dosyalar → Intro / Outro yukle</strong> (klasor: <code>${escapeHtml(folder)}</code>).`;
    return;
  }
  const meta = (appConfig?.outros || []).find((o) => o.id === id);
  if (!meta) {
    hint.textContent = "Secili kanalin intro / outrosu eklenir.";
    return;
  }
  const sec = (s) => (s ? ` (${s} sn)` : "");
  const bits = [
    meta.intro_file ? `intro${sec(meta.intro_duration_sec)} basa` : "",
    meta.file ? `outro${sec(meta.duration_sec)} sona` : "",
  ].filter(Boolean);
  hint.textContent = `${meta.label}: ${bits.join(", ")} eklenir.`;
}

function currentNicheId() {
  return $("niche")?.value || "tarih_gizem";
}

function nicheLabel(nicheId) {
  const n = (appConfig?.niches || []).find((x) => x.id === nicheId);
  return n?.label || nicheId;
}

function tracksForCurrentNiche(allTracks) {
  const niche = currentNicheId();
  const nicheOnly = (allTracks || []).filter((t) => t.category === niche);
  if (nicheOnly.length) return nicheOnly;
  return (allTracks || []).filter((t) => t.category === "genel");
}

function updateBgmNicheHint() {
  const hint = $("bgm-niche-hint");
  if (!hint) return;
  const mode = $("bgm-mode")?.value || "niche";
  const niche = currentNicheId();
  const cats = appConfig?.bgm_categories || [];
  const cat = cats.find((c) => c.id === niche);
  const count = cat?.track_count ?? 0;
  const pool = tracksForCurrentNiche(appConfig?.bgm_tracks || []);
  const total = pool.length;
  if (mode === "niche") {
    const sample = pool
      .slice(0, 3)
      .map((t) => t.label || t.filename)
      .join(", ");
    hint.textContent =
      total > 0
        ? `${nicheLabel(niche)}: ${total} parca — uretimde bunlardan biri secilir${sample ? ` (${sample}${total > 3 ? "…" : ""})` : ""}.`
        : `${nicheLabel(niche)} klasorunde parca yok — muzik eklenmez (data/bgm/${niche}/).`;
    hint.classList.toggle("hidden", false);
  } else if (mode === "random") {
    const all = (appConfig?.bgm_tracks || []).length;
    hint.textContent =
      all > 0
        ? `Tum niş klasorlerinden rastgele (${all} parca) — yalnizca senin MP3'lerin.`
        : "Henuz MP3 yok.";
    hint.classList.toggle("hidden", false);
  } else {
    hint.classList.toggle("hidden", mode === "none");
    if (mode === "custom" && count === 0 && total === 0) {
      hint.textContent = `Once MP3 ekle: data/bgm/${niche}/`;
    } else if (mode === "custom") {
      hint.textContent = `${total} parca listeleniyor (niş + genel).`;
    }
  }
}

function updateBgmTrackVisibility() {
  const mode = $("bgm-mode")?.value || "niche";
  const wrap = $("bgm-track-wrap");
  const preview = $("bgm-preview-wrap");
  if (wrap) wrap.classList.toggle("hidden", mode !== "custom");
  if (preview) preview.classList.toggle("hidden", mode !== "custom");
  updateBgmNicheHint();
}

function populateBgmTracks(tracks) {
  const sel = $("bgm-track");
  if (!sel) return;
  const cur = sel.value;
  const all = tracks || appConfig?.bgm_tracks || [];
  const items = tracksForCurrentNiche(all);
  const groups = new Map();
  items.forEach((t) => {
    const key = t.category_label || t.category || "Diger";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(t);
  });
  let html = '<option value="">— Parca sec —</option>';
  for (const [label, list] of groups) {
    html += `<optgroup label="${escapeHtml(label)}">`;
    html += list
      .map(
        (t) =>
          `<option value="${escapeHtml(t.id || t.filename)}">${escapeHtml(t.label || t.filename)}</option>`
      )
      .join("");
    html += "</optgroup>";
  }
  sel.innerHTML = html;
  if (items.some((t) => (t.id || t.filename) === cur)) sel.value = cur;
  else if (items.length === 1) sel.value = items[0].id || items[0].filename;
  else sel.value = "";
  refreshAllCustomSelects();
  updateBgmTrackVisibility();
}

function playBgmPreview() {
  const track = $("bgm-track")?.value;
  const audio = $("bgm-preview-audio");
  if (!track || !audio) return;
  audio.src = `/api/bgm/preview/${encodeURIComponent(track)}`;
  audio.play().catch(() => {});
}

function updateBgmVolumeLabel() {
  const v = $("bgm-volume");
  const lbl = $("bgm-volume-val");
  if (v && lbl) lbl.textContent = v.value;
}

async function archiveToGallery(
  taskId,
  subject,
  videos,
  aspect,
  script = "",
  publishPack = null,
  opts = {}
) {
  if (!taskId || archivedTaskIds.has(taskId)) return null;
  let pack = publishPack || null;
  const lang = opts.language || $("production-lang")?.value || "tr";
  const voiceMeta = opts.voice
    ? { tts_provider: opts.tts_provider || "rvc", voice: opts.voice }
    : getVoiceArchiveMeta(lang);
  const tts = opts.tts_provider || voiceMeta.tts_provider || $("tts-engine")?.value || "";
  const shouldNotify = opts.notify === true;
  const platform = opts.platform || $("platform")?.value || "";
  const niche = opts.niche || $("niche")?.value || "";
  try {
    // 1) Once baslik / aciklama / etiket — galeriye dusmeden / onizlemeden once
    const hasPack = !!(pack?.titles?.length || pack?.descriptions?.length || pack?.best_caption);
    if (!hasPack && (script || "").trim().length >= 10) {
      setStatus("Baslik / aciklama / etiket hazirlaniyor…");
      pack = await loadPublishReview(subject, script, aspect, lang, {
        silent: true,
        platform,
        niche,
      });
    }

    // 2) Paket hazir → galeri + onizleme
    setStatus("Galeriye kaydediliyor…");
    const r = await fetch("/api/gallery/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_id: taskId,
        subject,
        aspect,
        platform,
        language: lang,
        voice: voiceMeta.voice,
        niche,
        tts_provider: tts,
        videos,
        script,
        generate_caption: !(pack?.titles?.length || pack?.descriptions?.length || pack?.best_caption)
          && (script || "").trim().length >= 10,
        caption: pack?.best_caption || "",
        hashtags: collectYoutubeTagsFromPack(pack) || pack?.best_hashtags || "",
        title: pack?.best_title || "",
        publish_pack: pack || {},
        notify: false,
        notify_subject: opts.notify_subject || "",
        production_sec: Number(opts.production_sec || 0),
      }),
    });
    if (r.ok) {
      const data = await readApiJson(r);
      const created = data.items || [];
      const n = Number(data.archived || created.length || 0);
      // Bos arsiv = basarisiz — tekrar denenebilsin (archivedTaskIds ekleme)
      if (!n && !created.length) {
        setStatus("Galeri kaydi bos dondu — tekrar denenecek.");
        return null;
      }
      archivedTaskIds.add(taskId);
      lastArchivedTask = taskId;
      for (const entry of created) {
        if (entry.id) publishPackBackfillDone.add(entry.id);
        if (publishPackNeedsGenerate(entry)) {
          await ensureGalleryPublishPack(entry);
        }
      }
      void loadGallery();
      void loadGalleryStats();
      setStatus(
        `Video tamamlandi${opts.production_sec ? ` (${formatVcDuration(opts.production_sec)})` : ""} — galeri + yayin metinleri hazir.`
      );
      if (shouldNotify) {
        const msg =
          opts.notifyBody || `Video hazir: ${(opts.notify_subject || subject || "Video").slice(0, 80)}`;
        void notifyDone(opts.notifyTitle || "AkiFactory", msg);
      }
      return data;
    }
  } catch {
    setStatus("Video hazir (galeri kaydi basarisiz).");
  }
  return null;
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString("tr-TR");
  } catch {
    return iso || "";
  }
}

function aspectClass(aspect) {
  if (aspect === "16:9") return "landscape";
  if (aspect === "1:1") return "square";
  return "portrait";
}

function applyGalleryStats(s) {
  if (!s) return;
  const t = $("stat-total");
  const m = $("stat-month");
  const sz = $("stat-size");
  if (t) t.textContent = s.total_videos ?? 0;
  if (m) m.textContent = s.this_month ?? 0;
  if (sz) sz.textContent = s.total_size_mb ?? 0;
}

async function loadGalleryStats() {
  try {
    const r = await fetchWithTimeout("/api/gallery/stats", {}, 15000);
    if (!r.ok) return;
    applyGalleryStats(await readApiJson(r));
  } catch {
    /* ignore */
  }
}

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = "Kopyalandi";
    setTimeout(() => {
      btn.textContent = orig;
    }, 1500);
  });
}

const PLATFORM_BADGES = {
  tiktok: { label: "TikTok", cls: "tiktok" },
  youtube: { label: "YouTube", cls: "youtube" },
  youtube_shorts: { label: "Shorts", cls: "youtube_shorts" },
  instagram_reels: { label: "Reels", cls: "instagram_reels" },
  linkedin: { label: "LinkedIn", cls: "linkedin" },
};

async function shouldNotifyDesktop() {
  if (document.visibilityState === "hidden") return true;
  if (window.akifactory?.isWindowFocusedAsync) {
    return !(await window.akifactory.isWindowFocusedAsync());
  }
  if (window.akifactory?.isWindowFocused) {
    return !window.akifactory.isWindowFocused();
  }
  return !document.hasFocus();
}

async function notifyDone(title, body, dedupKey = "") {
  const key = dedupKey || `${title}::${body}`;
  const now = Date.now();
  const prev = notifyRecentKeys.get(key) || 0;
  if (now - prev < NOTIFY_DEDUP_MS) return;
  notifyRecentKeys.set(key, now);
  if (notifyRecentKeys.size > 80) {
    for (const [k, t] of notifyRecentKeys) {
      if (now - t > NOTIFY_DEDUP_MS) notifyRecentKeys.delete(k);
    }
  }

  const msg = `${title}: ${body}`;
  const preferDesktop = await shouldNotifyDesktop();
  let sent = false;
  try {
    if (window.akifactory?.showNotification) {
      const r = await window.akifactory.showNotification(title, body);
      if (r?.ok !== false) sent = true;
    } else if (window.pywebview?.api?.show_notification) {
      const r = await window.pywebview.api.show_notification(title, body);
      if (r?.ok !== false) sent = true;
    }
  } catch {
    /* fallback below */
  }
  if (!sent && typeof Notification !== "undefined" && Notification.permission === "granted") {
    try {
      new Notification(title, { body, icon: "/assets/icon.png" });
      sent = true;
    } catch {
      /* ignore */
    }
  }
  if (!sent || !preferDesktop) {
    showToast(msg, preferDesktop ? 3500 : 5500);
  }
}

function galleryPlatformLabel(id) {
  const pb = PLATFORM_BADGES[id];
  if (pb) return pb.label;
  const p = (appConfig?.platforms || []).find((x) => x.id === id);
  return p?.label || id || "—";
}

function galleryLangLabel(id) {
  const l = (appConfig?.production_languages || []).find((x) => x.id === id);
  return l?.label || id || "—";
}

function galleryTtsLabel(ttsProvider, voiceName) {
  const voice = (voiceName || "").trim();
  const tts = (ttsProvider || "").trim();
  if (voice && voice !== tts && voice !== "rvc" && voice !== "edge") {
    if (tts === "rvc") return `RVC — ${voice}`;
    if (tts === "edge") return voice;
    return voice;
  }
  const e = (appConfig?.tts_engines || []).find((x) => x.id === tts);
  return e?.label || tts || voice || "—";
}

function galleryDetailRankedList(items, textKey = "text", variant = "default") {
  if (!items?.length) {
    return '<p class="gallery-detail-empty">Kayit yok.</p>';
  }
  const isTitles = variant === "titles";
  const regenField = isTitles ? "title" : "description";
  return `<ul class="gallery-detail-list">${items
    .map((item, idx) => {
      const rank = item.rank ?? item.order ?? idx + 1;
      const why = item.why
        ? `<span class="gallery-detail-why">${escapeHtml(item.why)}</span>`
        : "";
      const textCls = isTitles
        ? `gallery-detail-text publish-title-text${publishTitleGlowClass(rank)}`
        : "gallery-detail-text";
      return `<li>
        <span class="gallery-detail-rank">${escapeHtml(String(rank))}</span>
        <div class="gallery-detail-item-body">
          <p class="${textCls}">${escapeHtml(item[textKey] || "")}</p>
          ${why}
        </div>
        <div class="gallery-detail-btn-col">
          <button type="button" class="btn-copy btn-sm btn-gallery-item-copy">Kopyala</button>
          <button type="button" class="btn-ghost btn-sm btn-gallery-field-regen" data-regen-field="${regenField}">Degistir</button>
        </div>
      </li>`;
    })
    .join("")}</ul>`;
}

/** Aciklama = merak metni; hemen altinda tam senaryo (ayri kopyala blogu yok). */
function galleryDetailDescriptionSectionHtml(item, { packing = false } = {}) {
  const pack = item.publish_pack || {};
  const descriptions = pack.descriptions?.length
    ? pack.descriptions
    : item.caption || pack.best_caption
      ? [{ rank: 1, text: item.caption || pack.best_caption }]
      : [];
  const script = (item.script || "").trim();
  const captionBlock =
    packing && !descriptions.length
      ? '<p class="gallery-detail-empty">Yayin paketi (baslik, aciklama, etiket) LLM ile hazirlaniyor…</p>'
      : galleryDetailRankedList(descriptions, "text", "descriptions");
  const alts = pack.caption_alternatives?.length
    ? `<p class="hint gallery-detail-alt-hint">A/B aciklama: ${escapeHtml(pack.caption_alternatives.map((a) => a.text).join(" · "))}</p>`
    : "";
  const scriptBlock = script
    ? `<div class="gallery-detail-desc-script">
        <p class="gallery-detail-desc-script-label">Senaryo</p>
        <p class="gallery-detail-script">${escapeHtml(script)}</p>
      </div>`
    : item.has_script
      ? `<p class="hint gallery-detail-alt-hint">Senaryo yukleniyor…</p>`
      : `<p class="hint gallery-detail-alt-hint">Bu kayitta senaryo metni yok.</p>`;
  return `<section class="gallery-detail-section gallery-detail-section-descriptions">
      <h4>Aciklama</h4>
      <p class="hint">Ustte yayin aciklamasi; altta videonun tam senaryosu.</p>
      ${captionBlock}
      ${alts}
      ${scriptBlock}
    </section>`;
}

function shareTipsNeedRegenerate(tips) {
  if (!tips?.length) return true;
  let weak = 0;
  for (const t of tips) {
    const tip = (t.tip || "").trim();
    const detail = (t.detail || "").trim();
    const cat = (t.category || "").trim();
    if (!detail && (tip === cat || tip.length < 20)) weak += 1;
    if (!detail && /^(En iyi paylasim|En uygun gun|Ilk 30|Ilk yorum|Caption ve|Capraz platform|Yeniden paylasim)/i.test(tip))
      weak += 1;
  }
  return weak >= Math.max(3, Math.ceil(tips.length / 2));
}

function galleryDetailShareTips(tips, lang, loading = false) {
  const lid = (lang || "tr").toLowerCase();
  if (lid !== "tr") {
    return '<p class="gallery-detail-empty">Yayin tavsiyeleri yalnizca Turkce videolarda uretilir.</p>';
  }
  if (loading) {
    return '<p class="gallery-detail-empty">Yayin tavsiyeleri LLM ile hazirlaniyor…</p>';
  }
  if (!tips?.length) {
    return '<p class="gallery-detail-empty">Yayin tavsiyesi kaydedilmedi. Yeni uretilen Turkce videolarda otomatik olusur.</p>';
  }
  if (shareTipsNeedRegenerate(tips)) {
    return '<p class="gallery-detail-empty">Tavsiyeler guncelleniyor (LLM)…</p>';
  }
  return `<ul class="gallery-detail-list">${tips
    .map((t) => {
      const category = t.category || "";
      const detail = t.detail
        ? `<span class="gallery-detail-tip-detail">${escapeHtml(t.detail)}</span>`
        : "";
      const catLbl = category
        ? `<span class="gallery-detail-tip-cat">${escapeHtml(category)}</span>`
        : "";
      const tipText = (t.tip || "").trim() || (t.detail || "").trim();
      return `<li>
        <span class="gallery-detail-rank">${escapeHtml(String(t.order ?? ""))}</span>
        <div class="gallery-detail-item-body">
          ${catLbl}
          <p class="gallery-detail-text">${escapeHtml(tipText)}</p>
          ${detail}
        </div>
        <div class="gallery-detail-btn-col">
          <button type="button" class="btn-copy btn-sm btn-gallery-item-copy">Kopyala</button>
          <button type="button" class="btn-ghost btn-sm btn-gallery-field-regen" data-regen-field="share_tips">Degistir</button>
        </div>
      </li>`;
    })
    .join("")}</ul>`;
}

function galleryDetailAllText(item) {
  const pack = item.publish_pack || {};
  const parts = [];
  const push = (label, text) => {
    if (text && String(text).trim()) parts.push(`${label}\n${String(text).trim()}`);
  };
  push("Konu", item.subject);
  push("Baslik", item.title || pack.best_title);
  (pack.titles || []).forEach((t, i) => push(`Baslik ${t.rank ?? i + 1}`, t.text));
  push("Aciklama (secilen)", item.caption || pack.best_caption);
  (pack.descriptions || []).forEach((d, i) => push(`Aciklama ${d.rank ?? i + 1}`, d.text));
  push("YouTube etiketleri", collectYoutubeTagsFromPack(pack, item));
  (pack.share_tips || []).forEach((t) => {
    const tip = [t.tip, t.detail].filter(Boolean).join("\n");
    push(`Tavsiye ${t.order ?? ""}`, tip);
  });
  if (item.script) push("Senaryo", item.script);
  const wangp = pack.wangp;
  const wangpPrompt = wangp?.prompt || wangp?.prompt_block;
  if (wangpPrompt) push("H3 Studio prompt", wangpPrompt);
  if (wangp?.negative_prompt) push("H3 Studio negative", wangp.negative_prompt);
  const fooocus = pack.fooocus;
  if (fooocus?.prompt) push("Qwen gorsel prompt", fooocus.prompt);
  if (fooocus?.negative_prompt) push("Qwen negatif prompt", fooocus.negative_prompt);
  return parts.join("\n\n");
}

async function prefetchGalleryPublishBackfill() {
  // Boot'ta 600KB+ galeri JSON cekme — backfill galeri acilinca gecikmeli baslar
  return;
}

async function checkRestoredQueue() {
  try {
    const r = await fetch("/api/queue");
    if (!r.ok) return;
    const q = await readApiJson(r);
    renderProductionQueue(q);
    if (suppressQueueBusyUi) {
      /* Kullanici az once durdurdu — eski "devam ediyor" bildirimi geri gelmesin */
    } else if (q.processing || (q.active_count > 0 && q.worker_alive)) {
      syncQueueActiveFromSnapshot(q);
      updateProductionStopUi();
      if (q.processing) {
        const msg =
          q.pending_count > 0
            ? `Uretim devam ediyor (${q.pending_count} bekleyen)`
            : "Uretim devam ediyor";
        clearQueueNotifications();
        pushQueueNotification(msg);
        showToast(msg, 5000);
      } else if (q.pending_count > 0) {
        clearQueueNotifications();
        pushQueueNotification(`${q.pending_count} video kuyrukta — basliyor`);
        showToast(`${q.pending_count} video kuyrukta — basliyor`, 4000);
      }
      startQueuePolling();
    } else if (q.pending_count > 0 && !q.worker_alive) {
      pushQueueNotification("Kuyruk isci yeniden baslatiliyor…", "warn");
      showToast("Kuyruk isci yeniden baslatiliyor…", 3000);
      startQueuePolling();
    }
  } catch {
    /* ignore */
  }
}

async function openGalleryEntryFolder(entryId) {
  const r = await fetch(`/api/gallery/${encodeURIComponent(entryId)}/open-folder`, { method: "POST" });
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, "Klasor acilamadi");
  showToast("Dosya klasorunde secildi");
}

async function captureGalleryThumbnail(entryId, frameIndex = null) {
  const body = frameIndex !== null && frameIndex !== undefined ? { frame_index: frameIndex } : {};
  const r = await fetchWithTimeout(
    `/api/gallery/${encodeURIComponent(entryId)}/thumbnail`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    120000
  );
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, "Kapak cekilemedi");
  const updated = data.item;
  if (updated) {
    const idx = galleryItemsCache.findIndex((x) => x.id === entryId);
    if (idx >= 0) galleryItemsCache[idx] = updated;
    if (galleryDetailItem?.id === entryId) {
      galleryDetailItem = updated;
      renderGalleryDetailBody(updated);
    }
  }
  return data;
}

function galleryMontageClipsHtml(clips) {
  if (!clips?.length) return "";
  return `<ul class="gallery-montage-clips">${clips
    .map(
      (c) =>
        `<li class="gallery-montage-clip">
        <span class="gallery-montage-clip-meta">
          <span class="gallery-montage-clip-kind">${c.kind === "image" ? "Gorsel" : "Klip"}</span>
          <span class="gallery-montage-clip-name">${escapeHtml(c.name)}</span>
          <span class="hint gallery-montage-clip-size">${escapeHtml(String(c.size_mb ?? ""))} MB</span>
        </span>
        <a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(c.url)}" download>Indir</a>
      </li>`
    )
    .join("")}</ul>`;
}

function galleryMontageAssetsSectionHtml(item) {
  const assets = item.assets || {};
  const hasAudio = !!assets.audio_url;
  const hasSub = !!assets.subtitle_url;
  const hasMusic = !!assets.music_url;
  const clips = assets.clips || [];
  const hasClips = clips.length > 0;
  if (!hasAudio && !hasSub && !hasMusic && !hasClips) {
    if (item.task_id) {
      return `<section class="gallery-detail-section gallery-detail-section-montage">
      <h4>Montaj dosyalari</h4>
      <p class="hint gallery-montage-missing">Ses, altyazi ve stok klipler bulunamadi. Motor gorev klasoru silinmis olabilir (<code>data/storage/tasks/</code>).</p>
    </section>`;
    }
    return "";
  }
  return `<section class="gallery-detail-section gallery-detail-section-montage">
      <h4>Montaj dosyalari</h4>
      <p class="hint">Ses, altyazi ve stok klipler — Premiere / DaVinci montajinda ayri katman olarak kullan.</p>
      <div class="btn-row btn-row-tight gallery-montage-actions">
        ${
          hasAudio
            ? `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(assets.audio_url)}" download>Sesi indir (MP3)</a>`
            : ""
        }
        ${
          hasSub
            ? `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(assets.subtitle_url)}" download>Altyaziyi indir (SRT)</a>`
            : ""
        }
        ${
          hasMusic
            ? `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(assets.music_url)}" download>Muzigi indir (MP3)</a>`
            : ""
        }
      </div>
      ${
        hasClips
          ? `<p class="hint gallery-montage-clips-title">Stok klipler / kaynak gorseller (${clips.length})</p>${galleryMontageClipsHtml(clips)}`
          : ""
      }
    </section>`;
}

function galleryThumbnailSectionHtml(item) {
  const has = item.has_thumbnail && item.thumbnail_url;
  const bust = has ? `?v=${encodeURIComponent(item.thumbnail || item.id)}` : "";
  const mainUrl = has ? `${item.thumbnail_url}${bust}` : "";
  const cands = item.thumbnail_candidates || [];
  const pickBtns =
    cands.length > 1
      ? `<div class="gallery-thumb-picks">${cands
          .map(
            (c) =>
              `<button type="button" class="gallery-thumb-pick${item.thumbnail_index === c.index ? " active" : ""}" data-thumb-pick="${c.index}" title="${escapeHtml(c.label)} (${c.time_sec}s)">
                <img src="${c.url}${bust}" alt="${escapeHtml(c.label)}" />
                <span>${escapeHtml(c.label)}</span>
              </button>`
          )
          .join("")}</div>`
      : "";
  return `<section class="gallery-detail-section gallery-detail-section-thumb">
      <h4>Kapak gorseli</h4>
      <p class="hint">Video kareleri ve AI kapakları — indirip kapak olarak kullanabilirsin.</p>
      ${item.ai_cover_status === "running" ? '<p class="hint">Qwen AI kapak hazırlanıyor…</p>' : ""}
      ${item.ai_cover_status === "error" ? `<p class="hint">AI kapak oluşturulamadı: ${escapeHtml(item.ai_cover_error || "Hata")}</p>` : ""}
      <div class="gallery-thumb-main-wrap">
        ${
          has
            ? `<img id="gallery-thumb-preview" class="gallery-thumb-preview" src="${mainUrl}" alt="Kapak" />`
            : `<p class="hint gallery-thumb-empty">Henuz kapak yok.</p>`
        }
      </div>
      ${pickBtns}
      <div class="btn-row btn-row-tight">
        <button type="button" class="btn-primary btn-sm" id="btn-gallery-thumb-capture">${has ? "Kapagi yenile" : "Kapak cek"}</button>
        ${
          has
            ? `<a class="btn-ghost btn-sm" href="/api/gallery/${encodeURIComponent(item.id)}/thumbnail/download" download>Kapagi indir</a>`
            : ""
        }
      </div>
    </section>`;
}

function bindGalleryThumbnailActions(item) {
  const body = $("gallery-detail-body");
  if (!body) return;
  $("btn-gallery-thumb-capture")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await captureGalleryThumbnail(item.id);
      showToast("Kapak gorseli hazir");
      void loadGallery();
    } catch (err) {
      showToast(err.message || "Kapak cekilemedi", 5000);
    } finally {
      btn.disabled = false;
    }
  });
  body.querySelectorAll("[data-thumb-pick]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const idx = Number(btn.dataset.thumbPick);
      if (Number.isNaN(idx)) return;
      btn.disabled = true;
      try {
        await captureGalleryThumbnail(item.id, idx);
        showToast("Kapak guncellendi");
        void loadGallery();
      } catch (err) {
        showToast(err.message || "Kapak secilemedi", 5000);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function galleryFooocusSectionHtml(item) {
  const pack = item.publish_pack || {};
  const fooocus = pack.fooocus;
  const loading = galleryFooocusLoading && galleryDetailItem?.id === item.id;
  const hasPrompt = !!(fooocus?.prompt);
  const variants = fooocus?.variants || [];
  const canGenerate =
    ((item.subject || "").trim().length >= 2 || (item.script || "").trim().length >= 10);
  const variantList =
    variants.length > 0
      ? `<ul class="gallery-detail-fooocus-variants">${variants
          .map(
            (v, i) =>
              `<li class="gallery-detail-fooocus-variant">
                <p class="gallery-detail-text">${escapeHtml(v)}</p>
                <button type="button" class="btn-copy btn-sm btn-gallery-fooocus-variant-copy" data-variant-idx="${i}">Kopyala</button>
              </li>`
          )
          .join("")}</ul>`
      : "";
  return `<section class="gallery-detail-section gallery-detail-section-fooocus">
      <h4>Qwen gorsel promptu</h4>
      <p class="hint">Video basligi ve senaryoya gore Qwen ile kapak/B-roll gorsel promptu.</p>
      ${
        loading
          ? `<p class="hint gallery-fooocus-loading">Qwen gorsel promptu uretiliyor…</p>`
          : hasPrompt
            ? `<p class="hint">Prompt</p>
      <p class="gallery-detail-text gallery-detail-fooocus-prompt">${escapeHtml(fooocus.prompt)}</p>
      <div class="gallery-detail-btn-col gallery-detail-btn-col-inline">
        <button type="button" class="btn-copy btn-sm" id="btn-gallery-copy-fooocus">Kopyala</button>
        <button type="button" class="btn-ghost btn-sm btn-gallery-prompt-regen" data-prompt-kind="fooocus" ${!canGenerate || loading ? "disabled" : ""}>Degistir</button>
      </div>
      ${
        fooocus.negative_prompt
          ? `<p class="hint">Negative prompt</p>
      <p class="gallery-detail-text gallery-detail-fooocus-neg">${escapeHtml(fooocus.negative_prompt)}</p>
      <div class="gallery-detail-btn-col gallery-detail-btn-col-inline">
        <button type="button" class="btn-copy btn-sm" id="btn-gallery-copy-fooocus-neg">Kopyala</button>
        <button type="button" class="btn-ghost btn-sm btn-gallery-prompt-regen" data-prompt-kind="fooocus" ${!canGenerate || loading ? "disabled" : ""}>Degistir</button>
      </div>`
          : ""
      }
      ${variantList}
      ${
        fooocus.fooocus_notes
          ? `<p class="hint gallery-detail-fooocus-notes">${escapeHtml(fooocus.fooocus_notes)}</p>`
          : ""
      }`
            : `<p class="hint gallery-fooocus-empty">${canGenerate ? "Henuz uretilmedi — asagidan olustur." : "Konu veya senaryo yok; prompt uretilemez."}</p>`
      }
      <div class="btn-row btn-row-tight gallery-fooocus-actions">
        <button type="button" class="btn-primary btn-sm" id="btn-gallery-fooocus-regen" ${!canGenerate || loading ? "disabled" : ""}>${hasPrompt ? "Yeniden olustur" : "Prompt uret"}</button>
      </div>
    </section>`;
}

async function regenerateGalleryFooocus(entryId, { silent = false } = {}) {
  galleryFooocusLoading = true;
  if (galleryDetailItem?.id === entryId) renderGalleryDetailBody(galleryDetailItem);
  try {
    const r = await fetchWithTimeout(
      `/api/gallery/${encodeURIComponent(entryId)}/fooocus`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style: "photorealistic",
          purpose: "thumbnail",
          variant_count: 1,
        }),
      },
      120000
    );
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Qwen gorsel promptu uretilemedi");
    const updated = data.item;
    galleryDetailItem = updated;
    const idx = galleryItemsCache.findIndex((i) => i.id === updated.id);
    if (idx >= 0) galleryItemsCache[idx] = updated;
    if (!$("gallery-detail-modal")?.classList.contains("hidden")) {
      renderGalleryDetailBody(updated);
    }
    if (!silent) showToast("Qwen gorsel promptu guncellendi");
    return updated;
  } catch (e) {
    if (!silent) showToast(e.message || "Qwen gorsel promptu uretilemedi", 5000);
    throw e;
  } finally {
    galleryFooocusLoading = false;
    if (galleryDetailItem?.id === entryId && !$("gallery-detail-modal")?.classList.contains("hidden")) {
      renderGalleryDetailBody(galleryDetailItem);
    }
  }
}

async function loadGalleryFooocusIfNeeded(item) {
  const fooocus = item.publish_pack?.fooocus;
  if (fooocus?.prompt) return;
  const canGenerate =
    (item.subject || "").trim().length >= 2 || (item.script || "").trim().length >= 10;
  if (!canGenerate) return;
  try {
    await regenerateGalleryFooocus(item.id, { silent: true });
  } catch {
    /* modal acik kalir — uretim sonunda genelde zaten gelir */
  }
}

async function regenerateShortGalleryMinimax(entryId) {
  galleryWangpLoading = true;
  if (galleryDetailItem?.id === entryId) renderGalleryDetailBody(galleryDetailItem);
  try {
    const r = await fetchWithTimeout(`/api/gallery/${encodeURIComponent(entryId)}/minimax`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        style: "dark_mystery",
        line_mode: "sliding_window",
        scene_count: 8,
        batch_count: 1,
      }),
    }, 180000);
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "H3 Studio promptu uretilemedi");
    galleryDetailItem = data.item;
    const idx = galleryItemsCache.findIndex((i) => i.id === data.item.id);
    if (idx >= 0) galleryItemsCache[idx] = data.item;
    renderGalleryDetailBody(data.item);
    showToast("H3 Studio promptu guncellendi");
  } catch (e) {
    showToast(e.message || "H3 Studio promptu uretilemedi", 5000);
  } finally {
    galleryWangpLoading = false;
    if (galleryDetailItem?.id === entryId) renderGalleryDetailBody(galleryDetailItem);
  }
}

function bindShortGalleryMinimaxActions(item) {
  const body = $("gallery-detail-body");
  body?.querySelector("#btn-gallery-wangp-regen")?.addEventListener("click", () => {
    void regenerateShortGalleryMinimax(item.id);
  });
  body?.querySelector("#btn-gallery-copy-wangp")?.addEventListener("click", (e) => {
    copyText(body.querySelector(".gallery-detail-wangp-prompt")?.textContent?.trim() || "", e.currentTarget);
  });
  body?.querySelector("#btn-gallery-copy-wangp-neg")?.addEventListener("click", (e) => {
    copyText(body.querySelector(".gallery-detail-wangp-neg")?.textContent?.trim() || "", e.currentTarget);
  });
}

function galleryWangpPromptText(wangp) {
  if (!wangp) return "";
  return (wangp.prompt || wangp.prompt_block || "").trim();
}

function galleryWangpSectionHtml(item) {
  const pack = item.publish_pack || {};
  const wangp = pack.wangp;
  const loading = galleryWangpLoading && galleryDetailItem?.id === item.id;
  const promptText = galleryWangpPromptText(wangp);
  const hasPrompt = !!promptText;
  const canGenerate =
    ((item.main_subject || item.subject || "").trim().length >= 2 ||
      (item.script || "").trim().length >= 10);
  return `<section class="gallery-detail-section gallery-detail-section-wangp">
      <h4>H3 Studio prompt</h4>
      <p class="hint">Sinematik SCENE / h3Prompt — Pinokio H3 Studio'ya yapistir.</p>
      ${
        loading
          ? `<p class="hint gallery-wangp-loading">H3 Studio promptu uretiliyor…</p>`
          : hasPrompt
            ? `<p class="hint">Prompt</p>
      <p class="gallery-detail-text gallery-detail-wangp-prompt">${escapeHtml(promptText)}</p>
      <div class="gallery-detail-btn-col gallery-detail-btn-col-inline">
        <button type="button" class="btn-copy btn-sm" id="btn-gallery-copy-wangp">Kopyala</button>
        <button type="button" class="btn-ghost btn-sm btn-gallery-prompt-regen" data-prompt-kind="wangp" ${!canGenerate || loading ? "disabled" : ""}>Degistir</button>
      </div>
      ${
        wangp.negative_prompt
          ? `<p class="hint">Negatif / yasaklar</p>
      <p class="gallery-detail-text gallery-detail-wangp-neg">${escapeHtml(wangp.negative_prompt)}</p>
      <div class="gallery-detail-btn-col gallery-detail-btn-col-inline">
        <button type="button" class="btn-copy btn-sm" id="btn-gallery-copy-wangp-neg">Kopyala</button>
        <button type="button" class="btn-ghost btn-sm btn-gallery-prompt-regen" data-prompt-kind="wangp" ${!canGenerate || loading ? "disabled" : ""}>Degistir</button>
      </div>`
          : ""
      }
      ${
        wangp.wgp_notes
          ? `<p class="hint gallery-detail-wangp-notes">${escapeHtml(wangp.wgp_notes)}</p>`
          : ""
      }`
            : `<p class="hint gallery-wangp-empty">${canGenerate ? "Henuz uretilmedi — asagidan olustur." : "Konu veya senaryo yok; prompt uretilemez."}</p>`
      }
      <div class="btn-row btn-row-tight gallery-wangp-actions">
        <button type="button" class="btn-primary btn-sm" id="btn-gallery-wangp-regen" ${!canGenerate || loading ? "disabled" : ""}>${hasPrompt ? "Yeniden olustur" : "Prompt uret"}</button>
      </div>
    </section>`;
}

async function regenerateLongformGalleryWangp(entryId, { silent = false } = {}) {
  galleryWangpLoading = true;
  if (galleryDetailItem?.id === entryId) {
    openLongformGalleryDetail(galleryDetailItem, { skipWangpLoad: true });
  }
  try {
    const r = await fetchWithTimeout(
      `/api/gallery/longform/${encodeURIComponent(entryId)}/wangp`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          style: "dark_mystery",
          line_mode: "sliding_window",
          scene_count: 5,
          batch_count: 1,
        }),
      },
      180000
    );
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "H3 Studio promptu uretilemedi");
    const updated = data.item;
    galleryDetailItem = updated;
    const idx = longformGalleryCache.findIndex((i) => i.id === updated.id);
    if (idx >= 0) longformGalleryCache[idx] = updated;
    if (!$("gallery-detail-modal")?.classList.contains("hidden")) {
      openLongformGalleryDetail(updated, { skipWangpLoad: true });
    }
    if (!silent) showToast("H3 Studio promptu guncellendi");
    return updated;
  } catch (e) {
    if (!silent) showToast(e.message || "H3 Studio promptu uretilemedi", 5000);
    throw e;
  } finally {
    galleryWangpLoading = false;
    if (galleryDetailItem?.id === entryId && !$("gallery-detail-modal")?.classList.contains("hidden")) {
      openLongformGalleryDetail(galleryDetailItem, { skipWangpLoad: true });
    }
  }
}

function bindLongformGalleryWangpActions(item) {
  const body = $("gallery-detail-body");
  if (!body) return;
  body.querySelector("#btn-gallery-wangp-regen")?.addEventListener("click", () => {
    void regenerateLongformGalleryWangp(item.id);
  });
  body.querySelector("#btn-gallery-copy-wangp")?.addEventListener("click", (e) => {
    const text = body.querySelector(".gallery-detail-wangp-prompt")?.textContent || "";
    copyText(text.trim(), e.currentTarget);
  });
  body.querySelector("#btn-gallery-copy-wangp-neg")?.addEventListener("click", (e) => {
    const text = body.querySelector(".gallery-detail-wangp-neg")?.textContent || "";
    copyText(text.trim(), e.currentTarget);
  });
  bindGalleryFieldRegenButtons(body, item);
}

async function loadLongformGalleryWangpIfNeeded(item) {
  if (galleryWangpLoading) return;
  const wangp = item.publish_pack?.wangp;
  if (galleryWangpPromptText(wangp)) return;
  const canGenerate =
    (item.main_subject || item.subject || "").trim().length >= 2 ||
    (item.script || "").trim().length >= 10;
  if (!canGenerate) return;
  try {
    await regenerateLongformGalleryWangp(item.id, { silent: true });
  } catch {
    /* modal acik kalir */
  }
}

function bindGalleryFooocusActions(item) {
  const body = $("gallery-detail-body");
  if (!body) return;
  $("btn-gallery-fooocus-regen")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      await regenerateGalleryFooocus(item.id);
    } catch {
      /* toast in regenerate */
    } finally {
      btn.disabled = false;
    }
  });
  $("btn-gallery-copy-fooocus")?.addEventListener("click", (e) => {
    const text = body.querySelector(".gallery-detail-fooocus-prompt")?.textContent || "";
    copyText(text.trim(), e.currentTarget);
  });
  $("btn-gallery-copy-fooocus-neg")?.addEventListener("click", (e) => {
    const text = body.querySelector(".gallery-detail-fooocus-neg")?.textContent || "";
    copyText(text.trim(), e.currentTarget);
  });
  body.querySelectorAll(".btn-gallery-fooocus-variant-copy").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.variantIdx);
      const variants = galleryDetailItem?.publish_pack?.fooocus?.variants || [];
      copyText(variants[idx] || "", btn);
    });
  });
}

function renderGalleryDetailBody(item) {
  const body = $("gallery-detail-body");
  if (!body) return;
  const pack = item.publish_pack || {};
  const titles = pack.titles?.length ? pack.titles : item.title ? [{ rank: 1, text: item.title }] : [];
  const youtubeTags = collectYoutubeTagsFromPack(pack, item);
  const tagWhy = pack.hashtag_sets?.[0]?.why || "";
  const dur =
    item.duration_sec > 0
      ? `${item.duration_sec} sn`
      : "—";
  const prodDur =
    item.production_sec > 0
      ? formatVcDuration(item.production_sec)
      : "—";
  const packingDesc =
    galleryPublishPackLoading &&
    galleryDetailItem?.id === item.id &&
    !(pack.descriptions?.length || item.caption || pack.best_caption);

  body.innerHTML = `
    <section class="gallery-detail-section gallery-detail-section-titles">
      <h4>Baslik</h4>
      ${galleryDetailRankedList(titles, "text", "titles")}
      ${
        pack.title_alternatives?.length
          ? `<p class="hint gallery-detail-alt-hint">A/B alternatif: ${escapeHtml(pack.title_alternatives.map((a) => a.text).join(" · "))}</p>`
          : ""
      }
    </section>
    ${galleryDetailDescriptionSectionHtml(item, { packing: packingDesc })}
    <section class="gallery-detail-section gallery-detail-section-hashtags">
      <h4>YouTube etiketleri</h4>
      ${
        galleryPublishPackLoading && galleryDetailItem?.id === item.id && !youtubeTags
          ? '<p class="publish-empty">Hazirlaniyor…</p>'
          : renderYoutubeTagsBlock(youtubeTags, { why: tagWhy, showHint: true })
      }
    </section>
    <section class="gallery-detail-section">
      <h4>Genel bilgiler</h4>
      <dl class="gallery-detail-meta">
        <div><dt>Platform</dt><dd>${escapeHtml(galleryPlatformLabel(item.platform))}</dd></div>
        <div><dt>Nis</dt><dd>${escapeHtml(nicheLabel(item.niche))}</dd></div>
        <div><dt>Dil</dt><dd>${escapeHtml(galleryLangLabel(item.language))}</dd></div>
        <div><dt>Seslendirme</dt><dd>${escapeHtml(galleryTtsLabel(item.tts_provider, item.voice))}</dd></div>
        <div><dt>Oran</dt><dd>${escapeHtml(item.aspect || "—")}</dd></div>
        <div><dt>Video suresi</dt><dd>${escapeHtml(dur)}</dd></div>
        <div><dt>Uretim suresi</dt><dd>${escapeHtml(prodDur)}</dd></div>
        <div><dt>Boyut</dt><dd>${escapeHtml(String(item.size_mb ?? "—"))} MB</dd></div>
        <div><dt>Olusturma</dt><dd>${escapeHtml(formatDate(item.created_at))}</dd></div>
      </dl>
    </section>
    ${galleryThumbnailSectionHtml(item)}
    ${galleryMontageAssetsSectionHtml(item)}
    ${galleryWangpSectionHtml(item)}
    ${galleryFooocusSectionHtml(item)}
    <section class="gallery-detail-section">
      <h4>Yayin tavsiyeleri</h4>
      ${galleryDetailShareTips(
        pack.share_tips,
        item.language,
        galleryShareTipsLoading &&
          galleryDetailItem?.id === item.id &&
          (!pack.share_tips?.length || shareTipsNeedRegenerate(pack.share_tips))
      )}
    </section>`;

  body.querySelectorAll(".btn-gallery-item-copy").forEach((btn) => {
    btn.addEventListener("click", async () => {
      // Aciklama kopyala = yayin metni + altindaki senaryo (TR ve EN ayni)
      if (btn.closest(".gallery-detail-section-descriptions")) {
        btn.disabled = true;
        try {
          const full = await ensureGalleryItemForCopy(item, {
            longform: isLongformGalleryItem(item),
          });
          const text = galleryDescriptionText(full);
          if (!text.trim()) {
            showToast("Aciklama / senaryo henuz yok", 3500);
            return;
          }
          copyText(text, btn);
        } finally {
          btn.disabled = false;
        }
        return;
      }
      const text = btn.closest("li")?.querySelector(".gallery-detail-text")?.textContent || "";
      copyText(text.trim(), btn);
    });
  });
  bindGalleryFieldRegenButtons(body, item);
  const tagsSection = body.querySelector(".gallery-detail-section-hashtags");
  if (tagsSection) bindYoutubeTagsCopy(tagsSection, youtubeTags);
  bindGalleryThumbnailActions(item);
  bindShortGalleryMinimaxActions(item);
  bindGalleryFooocusActions(item);
}

function applyGalleryPublishFieldResult(item, updated, longform) {
  if (longform) {
    const merged = { ...item, ...updated, _galleryKind: "longform" };
    const idx = longformGalleryCache.findIndex((x) => x.id === item.id);
    if (idx >= 0) longformGalleryCache[idx] = { ...longformGalleryCache[idx], ...merged };
    galleryDetailItem = merged;
    openLongformGalleryDetail(merged, { skipWangpLoad: true });
    return merged;
  }
  const idx = galleryItemsCache.findIndex((x) => x.id === item.id);
  if (idx >= 0) galleryItemsCache[idx] = { ...galleryItemsCache[idx], ...updated };
  galleryDetailItem = updated;
  renderGalleryDetailBody(updated);
  return updated;
}

/** Eski sunucu (publish-field yok) veya alan bazli hata icin: mevcut pack/tips API. */
async function regenerateGalleryPublishFieldFallback(item, field, longform) {
  const f = String(field || "title").toLowerCase();
  if (f === "share_tips" || f === "tips" || f === "tavsiye") {
    if (longform) {
      throw new Error("Uzun videoda yayin tavsiyesi icin Degistir henuz yok — baslik/aciklama/etiket deneyin");
    }
    const r = await fetchWithTimeout(
      `/api/gallery/${encodeURIComponent(item.id)}/share-tips`,
      { method: "POST" },
      180000
    );
    const data = await readApiJson(r).catch(() => ({}));
    if (!r.ok) throw apiError(data, "Yayin tavsiyeleri yenilenemedi");
    return data.item || { ...item, publish_pack: { ...(item.publish_pack || {}), share_tips: data.share_tips } };
  }
  const url = longform
    ? `/api/gallery/longform/${encodeURIComponent(item.id)}/publish-pack`
    : `/api/gallery/${encodeURIComponent(item.id)}/publish-pack`;
  const r = await fetchWithTimeout(url, { method: "POST" }, 180000);
  const data = await readApiJson(r).catch(() => ({}));
  if (!r.ok) throw apiError(data, "Yayin paketi yenilenemedi");
  return data.item || item;
}

async function regenerateGalleryPublishField(item, field, btn) {
  if (!item?.id) {
    showToast("Galeri kaydi bulunamadi", 5000);
    return;
  }
  const longform = isLongformGalleryItem(item);
  const url = longform
    ? `/api/gallery/longform/${encodeURIComponent(item.id)}/publish-field`
    : `/api/gallery/${encodeURIComponent(item.id)}/publish-field`;
  const prev = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Uretiliyor…";
  }
  try {
    const r = await fetchWithTimeout(
      url,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ field }),
      },
      180000
    );
    const data = await readApiJson(r).catch(() => ({}));
    let updated;
    if (r.ok) {
      updated = data.item || { ...item, ...(data.publish_pack ? { publish_pack: data.publish_pack } : {}) };
    } else if (r.status === 404) {
      // Calisan surec eski kodda olabilir — mevcut publish-pack / share-tips ile devam et
      updated = await regenerateGalleryPublishFieldFallback(item, field, longform);
    } else {
      throw apiError(data, data.detail || `HTTP ${r.status}`);
    }
    applyGalleryPublishFieldResult(item, updated, longform);
    showToast(r.ok ? "Alan yenilendi" : "Yenilendi (tum yayin metinleri)");
  } catch (e) {
    const msg = e.message || "Yenilenemedi";
    showToast(
      /not found/i.test(msg)
        ? "API bulunamadi — AkiFactory'yi kapatip yeniden acin, sonra tekrar deneyin"
        : msg,
      6000
    );
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prev || "Degistir";
    }
  }
}

function bindGalleryFieldRegenButtons(root, item) {
  root?.querySelectorAll?.(".btn-gallery-field-regen").forEach((btn) => {
    btn.addEventListener("click", () => {
      const field = btn.dataset.regenField || "title";
      void regenerateGalleryPublishField(item, field, btn);
    });
  });
  root?.querySelectorAll?.(".btn-gallery-prompt-regen").forEach((btn) => {
    btn.addEventListener("click", () => {
      const kind = btn.dataset.promptKind || "fooocus";
      if (kind === "wangp") {
        void regenerateLongformGalleryWangp(item.id).catch((e) =>
          showToast(e.message || "H3 Studio yenilenemedi", 5000)
        );
      } else {
        void regenerateGalleryFooocus(item.id).catch((e) =>
          showToast(e.message || "Qwen gorsel promptu yenilenemedi", 5000)
        );
      }
    });
  });
}

function scrollGalleryDetailToTitles() {
  const body = $("gallery-detail-body");
  if (!body) return;
  requestAnimationFrame(() => {
    body.scrollTop = 0;
    const titles = body.querySelector(".gallery-detail-section-titles");
    titles?.scrollIntoView({ block: "start" });
  });
}

async function openGalleryDetailModal(item) {
  galleryDetailItem = item;
  const modal = $("gallery-detail-modal");
  const title = $("gallery-detail-title");
  const sub = $("gallery-detail-subtitle");
  if (title) title.textContent = item.subject || item.title || "Video detaylari";
  if (sub) {
    const langLbl = galleryLangLabel(item.language);
    sub.textContent = `${galleryPlatformLabel(item.platform)} · ${langLbl} · ${formatDate(item.created_at)}`;
  }
  renderGalleryDetailBody(item);
  modal?.classList.remove("hidden");
  document.body.classList.add("modal-open");
  scrollGalleryDetailToTitles();
  // Senaryo listede gelmez — detayda eksikse tam kayit cek
  const needFull = !(item.script || "").trim() || !item.assets;
  if (needFull) {
    try {
      const r = await fetchWithTimeout(`/api/gallery/${encodeURIComponent(item.id)}`, {}, 45000);
      if (r.ok) {
        const full = await readApiJson(r);
        galleryDetailItem = { ...item, ...full };
        const cached = galleryItemsCache.find((x) => x.id === item.id);
        if (cached) {
          if (full.assets) cached.assets = full.assets;
          if (full.script) {
            cached.script = full.script;
            cached.has_script = true;
          }
        }
        renderGalleryDetailBody(galleryDetailItem);
      }
    } catch {
      /* montaj / senaryo opsiyonel */
    }
  }
  void loadGalleryPublishPackIfNeeded(galleryDetailItem || item).then(() =>
    loadGalleryShareTipsIfNeeded(galleryDetailItem || item)
  );
  void loadGalleryFooocusIfNeeded(galleryDetailItem || item);
}

function textLooksTurkish(text) {
  const t = String(text || "").trim();
  if (!t) return false;
  if (/[çğıöşüÇĞİÖŞÜ]/.test(t)) return true;
  const low = ` ${t.toLowerCase()} `;
  const markers = [
    " ve ",
    " bir ",
    " bu ",
    " icin ",
    " için ",
    " gizem",
    " tarih",
    " magara",
    " mağara",
    " sehir",
    " şehir",
    " yeralti",
    " yeraltı",
    " kesf",
    " keşf",
    " neden",
    " nasil",
    " nasıl",
  ];
  return markers.some((m) => low.includes(m));
}

function publishPackNeedsGenerate(item) {
  const pack = item?.publish_pack || {};
  const hasDesc = !!(pack.descriptions?.length || pack.best_caption);
  const lang = String(item?.language || "").toLowerCase();
  if (lang.startsWith("en")) {
    const title = item?.title || pack.best_title || "";
    const caption = item?.caption || pack.best_caption || "";
    if (!hasDesc) return true;
    if (/\(EN\)\s*$/i.test(title) || title === (item?.subject || "")) return true;
    if (textLooksTurkish(title) || textLooksTurkish(caption)) return true;
    return false;
  }
  return !hasDesc;
}

async function ensureGalleryPublishPack(item, { longform = false } = {}) {
  if (!item?.id) return item;
  if (!publishPackNeedsGenerate(item)) {
    publishPackBackfillDone.add(item.id);
    return item;
  }
  // TR sizintili EN paketlerini yeniden uret — eski "done" isaretini yoksay
  publishPackBackfillDone.delete(item.id);
  if (publishPackBackfillQueued.has(item.id)) return item;
  const script = (item.script || "").trim();
  if (script.length < 10 && !item.has_script) return item;

  publishPackBackfillQueued.add(item.id);
  try {
    const url = longform
      ? `/api/gallery/longform/${encodeURIComponent(item.id)}/publish-pack`
      : `/api/gallery/${encodeURIComponent(item.id)}/publish-pack`;
    const r = await fetchWithTimeout(url, { method: "POST" }, 180000);
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Yayin paketi uretilemedi");
    const updated = data.item || item;
    publishPackBackfillDone.add(item.id);
    if (longform) {
      const idx = longformGalleryCache.findIndex((i) => i.id === updated.id);
      if (idx >= 0) longformGalleryCache[idx] = { ...longformGalleryCache[idx], ...updated };
    } else {
      const idx = galleryItemsCache.findIndex((i) => i.id === updated.id);
      if (idx >= 0) galleryItemsCache[idx] = updated;
    }
    if (galleryDetailItem?.id === updated.id) {
      galleryDetailItem = { ...galleryDetailItem, ...updated };
      if (!$("gallery-detail-modal")?.classList.contains("hidden")) {
        if (longform) openLongformGalleryDetail(galleryDetailItem);
        else renderGalleryDetailBody(galleryDetailItem);
      }
    }
    return updated;
  } catch {
    return item;
  } finally {
    publishPackBackfillQueued.delete(item.id);
    releaseLlmResources();
  }
}

async function backfillGalleryPublishPacks(items, { longform = false } = {}) {
  const pool = items || (longform ? longformGalleryCache : galleryItemsCache);
  const pending = pool.filter(
    (it) =>
      publishPackNeedsGenerate(it) &&
      !publishPackBackfillDone.has(it.id) &&
      !publishPackBackfillQueued.has(it.id) &&
      ((it.script || "").trim().length >= 10 || it.has_script)
  );
  if (!pending.length || publishPackBackfillRunning) return;
  publishPackBackfillRunning = true;
  try {
    for (const item of pending) {
      const view = $("view-gallery");
      if (!view || view.hidden) break;
      await ensureGalleryPublishPack(item, { longform });
      await new Promise((resolve) => setTimeout(resolve, 400));
    }
    // Kartlari yerinde guncelle — tum galeriyi yeniden yukleme
  } finally {
    publishPackBackfillRunning = false;
  }
}

async function loadGalleryPublishPackIfNeeded(item) {
  if (!publishPackNeedsGenerate(item)) return;
  galleryPublishPackLoading = true;
  if (galleryDetailItem?.id === item.id) renderGalleryDetailBody(item);
  try {
    await ensureGalleryPublishPack(item);
  } finally {
    galleryPublishPackLoading = false;
    if (galleryDetailItem?.id === item.id && !$("gallery-detail-modal")?.classList.contains("hidden")) {
      renderGalleryDetailBody(galleryDetailItem || item);
    }
  }
}

async function loadGalleryShareTipsIfNeeded(item) {
  const lang = (item.language || "tr").toLowerCase();
  if (lang !== "tr") return;
  if (item.publish_pack?.share_tips?.length && !shareTipsNeedRegenerate(item.publish_pack.share_tips)) return;
  const script = (item.script || "").trim();
  if (script.length < 10) return;

  galleryShareTipsLoading = true;
  if (galleryDetailItem?.id === item.id) renderGalleryDetailBody(item);

  try {
    const r = await fetch(`/api/gallery/${item.id}/share-tips`, { method: "POST" });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Yayin tavsiyeleri uretilemedi");
    const updated = data.item || item;
    galleryDetailItem = updated;
    const idx = galleryItemsCache.findIndex((i) => i.id === updated.id);
    if (idx >= 0) galleryItemsCache[idx] = updated;
    galleryShareTipsLoading = false;
    if (!$("gallery-detail-modal")?.classList.contains("hidden")) {
      renderGalleryDetailBody(updated);
    }
  } catch (e) {
    galleryShareTipsLoading = false;
    if (galleryDetailItem?.id === item.id && !$("gallery-detail-modal")?.classList.contains("hidden")) {
      renderGalleryDetailBody(galleryDetailItem || item);
    }
    if (e?.message) setStatus(e.message, true);
  }
}

function closeGalleryDetailModal() {
  galleryDetailItem = null;
  $("gallery-detail-modal")?.classList.add("hidden");
  document.body.classList.remove("modal-open");
}

function titleCaseWords(text, lang = "tr") {
  const t = String(text || "").trim();
  if (!t) return "";
  const isTr = String(lang || "tr").toLowerCase().startsWith("tr");
  const trUp = { i: "İ", ı: "I", ğ: "Ğ", ü: "Ü", ş: "Ş", ö: "Ö", ç: "Ç" };
  const trLow = { I: "ı", İ: "i", Ğ: "ğ", Ü: "ü", Ş: "ş", Ö: "ö", Ç: "ç" };
  const lower = (s) =>
    isTr
      ? s
          .split("")
          .map((c) => trLow[c] || c)
          .join("")
          .toLowerCase()
      : s.toLowerCase();
  const upperFirst = (s) => {
    if (!s) return s;
    const c0 = s[0];
    const rest = lower(s.slice(1));
    if (isTr) {
      const u = trUp[c0] || trUp[c0.toLowerCase()] || c0.toUpperCase();
      return u + rest;
    }
    return c0.toUpperCase() + rest;
  };
  return t
    .split(/(\s+)/)
    .map((part) => {
      if (!part || /^\s+$/.test(part)) return part;
      const m = part.match(/^([^\p{L}\p{N}]*)(.*)$/u);
      if (!m) return part;
      const [, prefix, body] = m;
      if (!body) return part;
      if (/^\d/.test(body)) return part;
      const apos = body.match(/^([^'’]+)(['’])(.*)$/);
      if (apos) {
        return prefix + upperFirst(apos[1]) + apos[2] + lower(apos[3]);
      }
      return prefix + upperFirst(body);
    })
    .join("");
}

function galleryTitleText(item) {
  const raw = (item.title || item.main_subject || item.subject || "Video").trim();
  return titleCaseWords(raw, item.language || "tr");
}

function galleryDescriptionText(item) {
  const cap = (item.caption || item.publish_pack?.best_caption || "").trim();
  const script = (item.script || "").trim();
  const parts = [];
  if (cap) parts.push(cap);
  // Aciklama altinda tam senaryo (kisa + uzun video)
  if (script && script !== cap) parts.push(script);
  return parts.join("\n\n");
}

async function ensureGalleryItemForCopy(item, { longform = false } = {}) {
  if (!item?.id) return item;
  const hasScript = (item.script || "").trim().length >= 10;
  const hasCap = !!(item.caption || item.publish_pack?.best_caption);
  if (hasScript && hasCap) return item;
  try {
    const url = longform
      ? `/api/gallery/longform/${encodeURIComponent(item.id)}`
      : `/api/gallery/${encodeURIComponent(item.id)}`;
    const r = await fetchWithTimeout(url, {}, 20000);
    if (!r.ok) return item;
    const full = await readApiJson(r);
    if (!full || typeof full !== "object") return item;
    const merged = { ...item, ...full };
    const cache = longform ? longformGalleryCache : galleryItemsCache;
    const idx = (cache || []).findIndex((x) => x.id === item.id);
    if (idx >= 0) cache[idx] = { ...cache[idx], ...merged };
    if (galleryDetailItem?.id === item.id) {
      galleryDetailItem = { ...galleryDetailItem, ...merged };
    }
    return merged;
  } catch {
    return item;
  }
}

function galleryDescriptionPreview(item) {
  const cap = (item.caption || item.publish_pack?.best_caption || "").trim();
  const tags = (item.hashtags || item.publish_pack?.best_hashtags || "").trim();
  if (cap && tags) return `${cap} ${tags}`;
  return cap || tags || "—";
}

function galleryTagsText(item) {
  return collectYoutubeTagsFromPack(item.publish_pack, item);
}

function galleryHasTags(item) {
  return !!galleryTagsText(item).trim();
}

function clearAnalyzeImagePreviewUrls() {
  analyzeImageObjectUrls.forEach((u) => URL.revokeObjectURL(u));
  analyzeImageObjectUrls = [];
}

function updateAnalyzeImagePreview() {
  const input = $("analyze-image-files");
  const wrap = $("analyze-image-preview");
  const hint = $("analyze-image-hint");
  if (!input || !wrap) return;
  clearAnalyzeImagePreviewUrls();
  const files = Array.from(input.files || []).slice(0, 3);
  if (!files.length) {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    if (hint) {
      hint.textContent = "Video analizi → Genel bakis, Erisim veya Etkilesim sekmesinin ekran goruntusunu at.";
    }
    return;
  }
  if (hint) {
    hint.textContent = `${files.length} Studio goruntusu secildi — Genel bakis + Erisim birlikte daha iyi analiz verir.`;
  }
  wrap.innerHTML = files
    .map((file) => {
      const url = URL.createObjectURL(file);
      analyzeImageObjectUrls.push(url);
      return `<figure class="analyze-image-thumb"><img src="${url}" alt="${escapeHtml(file.name)}" /><figcaption>${escapeHtml(file.name)}</figcaption></figure>`;
    })
    .join("");
  wrap.classList.remove("hidden");
}

function populateAnalyzeVisionModels() {
  const sel = $("analyze-vision-model");
  const hint = $("analyze-vision-hint");
  const btn = $("btn-analyze-run");
  if (!sel || !appConfig) return;
  const models = appConfig.llm_vision_models || [];
  const def = appConfig.llm_default_vision || "";
  if (models.length) {
    sel.innerHTML = models
      .map(
        (m) =>
          `<option value="${escapeHtml(m.id)}" ${m.available ? "" : "disabled"}>${escapeHtml(m.label)}${m.available ? "" : " (AkiFactory.bat vision)"}</option>`
      )
      .join("");
  } else if (selectShowsLoading(sel)) {
    sel.innerHTML = `<option value="">Vision model yok</option>`;
  }
  const saved = localStorage.getItem(ANALYZE_VISION_KEY);
  const pick =
    saved && models.some((m) => m.id === saved && m.available)
      ? saved
      : def && models.some((m) => m.id === def && m.available)
        ? def
        : models.find((m) => m.available)?.id || "";
  if (pick) sel.value = pick;
  syncSelectUi(sel);
  const hasVision = models.some((m) => m.available);
  hint?.classList.toggle("hidden", hasVision);
  if (btn) btn.disabled = analyzeRunning || !hasVision;
}

function analyzePlatformLabel(id) {
  const p = (appConfig?.platforms || []).find((x) => x.id === id);
  return p?.label || id || "—";
}

function updateAnalyzeVideoPreview() {
  const sel = $("analyze-gallery-select");
  const meta = $("analyze-video-meta");
  const id = sel?.value || "";
  const item = analyzeGalleryCache.find((x) => x.id === id);
  if (!item) {
    if (meta) meta.textContent = "Hangi videonun istatistigi oldugunu secmek icin listeden sec.";
    return;
  }
  const title = galleryTitleText(item);
  const plat = analyzePlatformLabel(item.platform);
  const dur = item.duration_sec ? ` · ${item.duration_sec} sn` : "";
  if (meta) {
    meta.textContent = `Secili video: ${title} · ${plat}${dur}`;
  }
}

async function loadAnalyzeGalleryOptions() {
  const sel = $("analyze-gallery-select");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = `<option value="">Yukleniyor…</option>`;
  try {
    const r = await fetchWithTimeout("/api/gallery", {}, 20000);
    const data = await readApiJson(r);
    const items = data.items || [];
    analyzeGalleryCache = items;
    if (!items.length) {
      sel.innerHTML = `<option value="">Galeride video yok</option>`;
      syncSelectUi(sel);
      updateAnalyzeVideoPreview();
      return;
    }
    sel.innerHTML =
      `<option value="">— Video sec —</option>` +
      items
        .map((item) => {
          const label = `${galleryTitleText(item)} (${formatDate(item.created_at)})`;
          return `<option value="${escapeHtml(item.id)}">${escapeHtml(label)}</option>`;
        })
        .join("");
    if (prev && items.some((x) => x.id === prev)) sel.value = prev;
    syncSelectUi(sel);
    updateAnalyzeVideoPreview();
  } catch (e) {
    sel.innerHTML = `<option value="">Yuklenemedi</option>`;
    syncSelectUi(sel);
    setAnalyzeStatus(e.message || "Galeri yuklenemedi", true);
  }
}

function setAnalyzeStatus(msg, isErr = false) {
  const el = $("analyze-status");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("err", !!isErr);
}

function renderAnalyzeList(elId, items) {
  const ul = $(elId);
  if (!ul) return;
  const list = (items || []).filter(Boolean);
  if (!list.length) {
    ul.innerHTML = `<li class="hint">—</li>`;
    return;
  }
  ul.innerHTML = list.map((t) => `<li>${escapeHtml(t)}</li>`).join("");
}

function renderAnalyzeReport(report) {
  const summary = $("analyze-summary");
  const sections = $("analyze-sections");
  const rawWrap = $("analyze-raw-wrap");
  const rawEl = $("analyze-raw");
  if (!report) {
    if (summary) {
      summary.textContent = "Henuz analiz yok.";
      summary.classList.add("hint");
    }
    sections?.classList.add("hidden");
    rawWrap?.classList.add("hidden");
    return;
  }
  const sum = (report.summary || "").trim();
  if (summary) {
    summary.textContent = sum || "Analiz tamamlandi.";
    summary.classList.toggle("hint", !sum);
  }
  renderAnalyzeList("analyze-strengths", report.strengths);
  renderAnalyzeList("analyze-weaknesses", report.weaknesses);
  renderAnalyzeList("analyze-stats-insights", report.stats_insights);
  renderAnalyzeList("analyze-recommendations", report.recommendations);
  renderAnalyzeList("analyze-next-video", report.next_video);
  sections?.classList.remove("hidden");
  if (rawEl) rawEl.textContent = report.raw || "";
  rawWrap?.classList.toggle("hidden", !(report.raw || "").trim());
}

async function runAnalyze() {
  if (analyzeRunning) return;
  const galleryId = $("analyze-gallery-select")?.value || "";
  if (!galleryId) {
    showToast("Once galeriden videoyu sec");
    return;
  }
  const input = $("analyze-image-files");
  const files = Array.from(input?.files || []).slice(0, 3);
  if (!files.length) {
    showToast("YouTube Studio ekran goruntusunu yukle");
    return;
  }
  const visionModel = $("analyze-vision-model")?.value || "";
  const btn = $("btn-analyze-run");
  analyzeRunning = true;
  if (btn) btn.disabled = true;
  setAnalyzeStatus("Studio istatistikleri okunuyor… (20-60 sn)");
  try {
    const form = new FormData();
    form.append("gallery_id", galleryId);
    files.forEach((f) => form.append("files", f, f.name));
    if (visionModel) form.append("vision_model", visionModel);
    form.append("note", ($("analyze-image-note")?.value || "").trim());
    form.append("save_history", "true");

    const r = await fetchWithTimeout("/api/analyze/stats", { method: "POST", body: form }, 300000);
    const data = await readApiJson(r);
    if (!r.ok) {
      throw apiError(data, `Analiz basarisiz (HTTP ${r.status})`);
    }
    renderAnalyzeReport(data.report);
    const model = data.vision_model || "";
    const subj = data.subject || "Video";
    setAnalyzeStatus(`Analiz tamam: ${subj} (${model})`);
    showToast("Istatistik analizi hazir");
    void loadAnalyzeHistory(galleryId);
  } catch (e) {
    setAnalyzeStatus(e.message || "Analiz basarisiz", true);
    showToast(e.message || "Analiz basarisiz", 6000);
  } finally {
    analyzeRunning = false;
    populateAnalyzeVisionModels();
    if (btn && !analyzeRunning) btn.disabled = false;
  }
}

async function loadAnalyzeHistory(galleryId = null) {
  const ul = $("analyze-history-list");
  if (!ul) return;
  const qs = new URLSearchParams();
  const gid = galleryId || $("analyze-gallery-select")?.value || "";
  if (gid) qs.set("gallery_id", gid);
  qs.set("limit", "15");
  try {
    const r = await fetchWithTimeout(`/api/analyze/history?${qs}`, {}, 15000);
    const data = await readApiJson(r);
    const items = data.items || [];
    if (!items.length) {
      ul.innerHTML = `<li class="hint">Henuz kayit yok.</li>`;
      return;
    }
    ul.innerHTML = items
      .map((item) => {
        const sum = escapeHtml((item.summary || item.subject || "Analiz").slice(0, 120));
        const when = formatDate(item.created_at);
        const kind =
          item.source_type === "stats" || item.image_mode === "youtube_studio"
            ? '<span class="analyze-kind-badge">Istatistik</span> '
            : item.source_type === "gallery"
              ? '<span class="analyze-kind-badge">Video</span> '
              : "";
        return `<li class="analyze-history-item" data-analyze-id="${escapeHtml(item.id)}">
          <button type="button" class="analyze-history-btn" data-load-analyze="${escapeHtml(item.id)}">
            <strong>${kind}${sum}</strong>
            <span class="hint">${when}</span>
          </button>
        </li>`;
      })
      .join("");
    ul.querySelectorAll("[data-load-analyze]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const rec = items.find((x) => x.id === btn.dataset.loadAnalyze);
        if (rec) {
          renderAnalyzeReport(rec);
          if (rec.gallery_id && $("analyze-gallery-select")) {
            $("analyze-gallery-select").value = rec.gallery_id;
            syncSelectUi($("analyze-gallery-select"));
            updateAnalyzeVideoPreview();
          }
          if (rec.youtube_stats && $("analyze-image-note") && !($("analyze-image-note").value || "").trim()) {
            $("analyze-image-note").value = rec.youtube_stats;
          }
        }
      });
    });
  } catch {
    ul.innerHTML = `<li class="hint">Gecmis yuklenemedi.</li>`;
  }
}

async function openAnalyzeForVideo(itemId) {
  if (!itemId) return;
  switchTab("analyze");
  await loadAnalyzeGalleryOptions();
  const sel = $("analyze-gallery-select");
  if (sel && analyzeGalleryCache.some((x) => x.id === itemId)) {
    sel.value = itemId;
    syncSelectUi(sel);
    updateAnalyzeVideoPreview();
    void loadAnalyzeHistory(itemId);
  }
}

function galleryCopyRowsHtml(item) {
  const titleText = galleryTitleText(item);
  const descPreview = galleryDescriptionPreview(item);
  const hasDesc = !!(item.caption || item.publish_pack?.best_caption || item.hashtags || item.publish_pack?.best_hashtags);
  const packing = publishPackNeedsGenerate(item) && ((item.script || "").trim().length >= 10 || item.has_script);
  const descRow = hasDesc
    ? `<div class="gallery-copy-row">
            <span class="gallery-copy-label">Aciklama</span>
            <p class="gallery-copy-text gallery-copy-desc" title="${escapeHtml(descPreview)}">${escapeHtml(descPreview)}</p>
            <button type="button" class="btn-copy btn-copy-row" data-copy-desc="${item.id}">Kopyala</button>
          </div>`
    : packing
      ? `<div class="gallery-copy-row">
            <span class="gallery-copy-label">Aciklama</span>
            <p class="gallery-copy-text gallery-copy-muted">Yayin metni hazirlaniyor…</p>
          </div>`
      : "";
  const tagsRow = galleryHasTags(item)
    ? `<div class="gallery-copy-row">
            <span class="gallery-copy-label">Etiket</span>
            <p class="gallery-copy-text gallery-copy-muted">Etiketler gizli — kopyalanabilir</p>
            <button type="button" class="btn-copy btn-copy-row" data-copy-tags="${item.id}">Kopyala</button>
          </div>`
    : "";
  return `<div class="gallery-copy-block">
          <div class="gallery-copy-row">
            <span class="gallery-copy-label">Baslik</span>
            <p class="gallery-copy-text" title="${escapeHtml(titleText)}">${escapeHtml(titleText)}</p>
            <button type="button" class="btn-copy btn-copy-row" data-copy-title="${item.id}">Kopyala</button>
          </div>
          ${descRow}
          ${tagsRow}
        </div>`;
}

function bindGalleryCopyButtons(root, cache) {
  if (!root) return;
  root.querySelectorAll("[data-copy-title]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = cache.find((x) => x.id === btn.dataset.copyTitle);
      if (item) copyText(galleryTitleText(item), btn);
    });
  });
  root.querySelectorAll("[data-copy-desc]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      let item = cache.find((x) => x.id === btn.dataset.copyDesc);
      if (!item) return;
      btn.disabled = true;
      try {
        const longform = galleryViewMode === "long" || isLongformGalleryItem(item);
        item = await ensureGalleryItemForCopy(item, { longform });
        const text = galleryDescriptionText(item);
        if (!text.trim()) {
          showToast("Aciklama / senaryo henuz yok", 3500);
          return;
        }
        copyText(text, btn);
      } finally {
        btn.disabled = false;
      }
    });
  });
  root.querySelectorAll("[data-copy-tags]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = cache.find((x) => x.id === btn.dataset.copyTags);
      if (item) copyText(galleryTagsText(item), btn);
    });
  });
}

async function fixEnGalleryTitlesIfNeeded() {
  if (galleryEnTitlesFixStarted) return;
  const needs = (galleryItemsCache || []).filter(
    (i) =>
      String(i.language || "")
        .toLowerCase()
        .startsWith("en") && publishPackNeedsGenerate(i)
  );
  if (!needs.length) return;
  galleryEnTitlesFixStarted = true;
  try {
    showToast(`${needs.length} EN baslik Ingilizceye cevriliyor…`, 5000);
    const r = await fetchWithTimeout(
      "/api/gallery/fix-en-titles?limit=40",
      { method: "POST" },
      600000
    );
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "EN baslik duzeltilemedi");
    (data.ids || []).forEach((id) => {
      publishPackBackfillDone.delete(id);
      publishPackBackfillQueued.delete(id);
    });
    if (data.fixed > 0) {
      showToast(`${data.fixed} EN baslik duzeltildi`);
      // Kalan varsa sonraki galeri yuklenmesinde devam et
      if ((data.remaining || 0) > 0) galleryEnTitlesFixStarted = false;
      void loadGallery();
      void loadGalleryStats();
    } else if (data.errors?.length) {
      galleryEnTitlesFixStarted = false;
      showToast(data.errors[0]?.error || "EN baslik duzeltilemedi", 6000);
    }
  } catch (e) {
    galleryEnTitlesFixStarted = false;
    showToast(e.message || "EN baslik duzeltilemedi", 6000);
  }
}

function updateGalleryBulkUi() {
  const n = gallerySelectedIds.size;
  const delBtn = $("btn-gallery-bulk-delete");
  const allBtn = $("btn-gallery-select-all");
  if (delBtn) {
    delBtn.disabled = n === 0 || galleryBulkDeleting;
    delBtn.textContent = n ? `Secilenleri sil (${n})` : "Secilenleri sil";
  }
  const total =
    galleryViewMode === "long"
      ? (longformGalleryCache || []).length
      : (galleryItemsCache || []).length;
  if (allBtn) {
    allBtn.textContent =
      total > 0 && n === total ? "Secimi kaldir" : "Tumunu sec";
  }
}

function clearGallerySelection() {
  gallerySelectedIds.clear();
  document.querySelectorAll(".gallery-select").forEach((el) => {
    el.checked = false;
  });
  document.querySelectorAll(".gallery-card.is-selected").forEach((el) => {
    el.classList.remove("is-selected");
  });
  updateGalleryBulkUi();
}

function bindGallerySelection(grid) {
  if (!grid) return;
  grid.querySelectorAll(".gallery-select").forEach((el) => {
    el.addEventListener("change", () => {
      const id = el.dataset.id;
      if (!id) return;
      const card = el.closest(".gallery-card");
      if (el.checked) {
        gallerySelectedIds.add(id);
        card?.classList.add("is-selected");
      } else {
        gallerySelectedIds.delete(id);
        card?.classList.remove("is-selected");
      }
      updateGalleryBulkUi();
    });
  });
  updateGalleryBulkUi();
}

function releaseOutputIfShowing(ids) {
  if (!outputGalleryId || !ids.map(String).includes(String(outputGalleryId))) return;
  releaseGalleryCardVideo($("preview"));
  clearPreview();
}

function releaseGalleryCardVideo(card) {
  const vid = card?.querySelector("video");
  if (!vid) return;
  try {
    vid.pause();
  } catch {
    /* ignore */
  }
  vid.removeAttribute("src");
  try {
    vid.load();
  } catch {
    /* ignore */
  }
}

function bindGalleryCardMedia(root) {
  if (!root) return;
  root.querySelectorAll(".gallery-media[data-stream]").forEach((wrap) => {
    if (wrap.dataset.boundPlay === "1") return;
    wrap.dataset.boundPlay = "1";
    const play = () => {
      const stream = wrap.getAttribute("data-stream");
      if (!stream || wrap.querySelector("video")) return;
      const poster = wrap.querySelector(".gallery-poster");
      const posterSrc = poster?.getAttribute("src") || "";
      wrap.innerHTML = `<video controls playsinline autoplay preload="metadata" src="${stream}"${
        posterSrc ? ` poster="${posterSrc}"` : ""
      }></video>`;
    };
    wrap.querySelector(".gallery-play-btn")?.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      play();
    });
    wrap.querySelector(".gallery-poster")?.addEventListener("click", (ev) => {
      ev.preventDefault();
      play();
    });
  });
}

function galleryCardMediaHtml(item) {
  const stream = escapeHtml(item.stream_url || "");
  const thumb =
    item.has_thumbnail && item.thumbnail_url
      ? `<img class="gallery-poster" loading="lazy" decoding="async" src="${escapeHtml(item.thumbnail_url)}" alt="" />`
      : `<div class="gallery-poster gallery-poster-empty" aria-hidden="true">Onizleme</div>`;
  return `<div class="gallery-media" data-stream="${stream}">
        ${thumb}
        <button type="button" class="gallery-play-btn" aria-label="Oynat">▶</button>
      </div>`;
}

function toggleGallerySelectAll() {
  const cache = galleryViewMode === "long" ? longformGalleryCache : galleryItemsCache;
  const ids = (cache || []).map((x) => x.id).filter(Boolean);
  if (!ids.length) return;
  const allOn = ids.every((id) => gallerySelectedIds.has(id));
  gallerySelectedIds.clear();
  if (!allOn) ids.forEach((id) => gallerySelectedIds.add(id));
  document.querySelectorAll(".gallery-select").forEach((el) => {
    const on = gallerySelectedIds.has(el.dataset.id);
    el.checked = on;
    el.closest(".gallery-card")?.classList.toggle("is-selected", on);
  });
  updateGalleryBulkUi();
}

async function bulkDeleteGallerySelection() {
  const ids = [...gallerySelectedIds];
  if (!ids.length || galleryBulkDeleting) return;
  const long = galleryViewMode === "long";
  const msg = long
    ? `${ids.length} uzun video klasoru kalici silinsin mi?`
    : `${ids.length} video galeriden silinsin mi?`;
  if (!confirm(msg)) return;

  galleryBulkDeleting = true;
  updateGalleryBulkUi();
  const btn = $("btn-gallery-bulk-delete");
  if (btn) btn.textContent = "Siliniyor…";

  document.querySelectorAll(".gallery-card.is-selected").forEach((card) => {
    releaseGalleryCardVideo(card);
  });
  if (!long) releaseOutputIfShowing(ids);

  try {
    const url = long ? "/api/gallery/longform/bulk-delete" : "/api/gallery/bulk-delete";
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    });
    const data = await readApiJson(r).catch(() => ({}));
    if (!r.ok) throw apiError(data, "Toplu silme basarisiz");
    const deleted = data.deleted || [];
    const failed = data.failed || [];
    if (failed.length) {
      showToast(
        `${deleted.length} silindi, ${failed.length} basarisiz (dosya acik olabilir)`,
        7000
      );
    } else {
      showToast(`${deleted.length} kayit silindi`);
    }
    clearGallerySelection();
    removeGalleryCardsLocally(deleted);
    void loadGalleryStats();
    if (long) void loadLongformGallery();
    if (!long) refreshProducedAfterGalleryDelete();
    // Basarisiz kalanlar icin yalniz soft yenile
    if (failed.length) {
      if (long) void loadLongformGallery();
      else void loadGallery({ soft: true });
    }
  } catch (e) {
    showToast(e.message || "Toplu silme basarisiz", 6000);
  } finally {
    galleryBulkDeleting = false;
    updateGalleryBulkUi();
  }
}

function removeGalleryCardsLocally(ids) {
  const idSet = new Set((ids || []).map(String));
  if (!idSet.size) return;
  idSet.forEach((id) => {
    gallerySelectedIds.delete(id);
    const card = document.querySelector(`.gallery-card[data-gallery-id="${CSS.escape(id)}"]`);
    if (card) {
      releaseGalleryCardVideo(card);
      card.remove();
    }
  });
  galleryItemsCache = (galleryItemsCache || []).filter((it) => !idSet.has(String(it.id)));
  longformGalleryCache = (longformGalleryCache || []).filter((it) => !idSet.has(String(it.id)));
  const grid = $("gallery-grid");
  if (grid && !grid.querySelector(".gallery-card")) {
    grid.innerHTML =
      galleryViewMode === "long"
        ? '<p class="gallery-empty">Henuz uzun video paketi yok. Uretim sekmesinden uzun video olustur.</p>'
        : '<p class="gallery-empty">Henuz galeride video yok. Uretim sekmesinden bir video olustur.</p>';
  }
  updateGalleryBulkUi();
}

function refreshProducedAfterGalleryDelete() {
  // Arka planda — silme UI'sini bekletme
  setTimeout(() => {
    void loadProducedTopics();
    void loadTopicMemoryHint();
    if (!currentVideoUrl) void showLatestOutput();
  }, 50);
}

async function loadGallery(opts = {}) {
  const soft = !!opts.soft;
  const grid = $("gallery-grid");
  if (!grid) return;
  if (!soft) clearGallerySelection();
  if (!soft) grid.innerHTML = '<p class="gallery-empty">Yukleniyor...</p>';
  const plat = $("gallery-filter-platform")?.value || "";
  const niche = $("gallery-filter-niche")?.value || "";
  const qs = new URLSearchParams();
  if (plat) qs.set("platform", plat);
  if (niche) qs.set("niche", niche);
  if (!soft) qs.set("include_stats", "1");
  try {
    const r = await fetchWithTimeout(`/api/gallery?${qs.toString()}`, {}, 45000);
    if (!r.ok) {
      if (!soft) {
        grid.innerHTML = `<p class="gallery-empty">Galeri yuklenemedi (HTTP ${r.status}). Yenile butonuna basin.</p>`;
      }
      return;
    }
    const data = await readApiJson(r);
    if (data.stats) applyGalleryStats(data.stats);
    const items = data.items || [];
    galleryItemsCache = items;
    if (!items.length) {
      galleryItemsCache = [];
      grid.innerHTML =
        '<p class="gallery-empty">Henuz galeride video yok. Uretim sekmesinden bir video olustur.</p>';
      updateGalleryBulkUi();
      return;
    }
    if (!soft) {
      setTimeout(() => {
        if ($("view-gallery") && !$("view-gallery").hidden) {
          void fixEnGalleryTitlesIfNeeded();
        }
      }, 6000);
    }
    grid.innerHTML = items
      .map((item) => {
        const titleText = galleryTitleText(item);
        const pb = PLATFORM_BADGES[item.platform] || null;
        const badge = pb
          ? `<span class="platform-badge ${pb.cls}">${pb.label}</span>`
          : "";
        const langBadge = item.language
          ? `<span class="platform-badge lang-badge">${escapeHtml(galleryLangLabel(item.language))}</span>`
          : "";
        const copyRows = galleryCopyRowsHtml(item);
        const prodMeta =
          item.production_sec > 0 ? ` · uretim ${formatVcDuration(item.production_sec)}` : "";
        const vidMeta = item.duration_sec > 0 ? ` · ${item.duration_sec} sn video` : "";
        return `
      <article class="gallery-card ${aspectClass(item.aspect)}" data-gallery-id="${item.id}">
        <label class="gallery-check">
          <input type="checkbox" class="gallery-select" data-id="${item.id}" />
          <span>Sec</span>
        </label>
        ${galleryCardMediaHtml(item)}
        <div class="gallery-meta">
          ${badge}${langBadge}
          <h3>${escapeHtml(item.subject || titleText)}</h3>
          <time>${formatDate(item.created_at)} · ${item.size_mb || "?"} MB${vidMeta}${prodMeta}</time>
          ${copyRows}
          <div class="gallery-actions">
            <button type="button" class="btn-ghost btn-sm btn-details" data-gallery-detail="${item.id}">Detaylar</button>
            <button type="button" class="btn-ghost btn-sm" data-gallery-thumb="${item.id}">${item.has_thumbnail ? "Kapak" : "Kapak cek"}</button>
            <button type="button" class="btn-ghost btn-sm" data-analyze-video="${item.id}">Istatistik</button>
            <button type="button" class="btn-ghost btn-sm" data-save-url="${escapeHtml(item.download_url)}" data-save-name="${escapeHtml(videoFilenameFromSubject(item.subject))}">Indir</button>
            <button type="button" class="danger btn-sm" data-delete="${item.id}">Sil</button>
          </div>
        </div>
      </article>`;
      })
      .join("");

    grid.querySelectorAll("[data-gallery-detail]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = galleryItemsCache.find((x) => x.id === btn.dataset.galleryDetail);
        if (item) openGalleryDetailModal(item);
      });
    });
    grid.querySelectorAll("[data-gallery-thumb]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.dataset.galleryThumb;
        const item = galleryItemsCache.find((x) => x.id === id);
        if (item?.has_thumbnail) {
          openGalleryDetailModal(item);
          return;
        }
        btn.disabled = true;
        try {
          await captureGalleryThumbnail(id);
          showToast("Kapak gorseli hazir");
          void loadGallery({ soft: true });
        } catch (e) {
          showToast(e.message || "Kapak cekilemedi", 5000);
        } finally {
          btn.disabled = false;
        }
      });
    });
    grid.querySelectorAll("[data-analyze-video]").forEach((btn) => {
      btn.addEventListener("click", () => void openAnalyzeForVideo(btn.dataset.analyzeVideo));
    });
    grid.querySelectorAll("[data-save-url]").forEach((btn) => {
      btn.addEventListener("click", () => {
        saveVideoFile(btn.dataset.saveUrl, btn.dataset.saveName);
      });
    });
    grid.querySelectorAll("[data-delete]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Bu videoyu galeriden silinsin mi?")) return;
        const id = btn.dataset.delete;
        const card = btn.closest(".gallery-card");
        releaseGalleryCardVideo(card);
        releaseOutputIfShowing([id]);
        btn.disabled = true;
        // Aninda UI'dan dus — sunucu yanitini beklemeden his
        removeGalleryCardsLocally([id]);
        try {
          const r = await fetch(`/api/gallery/${encodeURIComponent(id)}`, {
            method: "DELETE",
          });
          const data = await readApiJson(r).catch(() => ({}));
          if (!r.ok) throw apiError(data, data.detail || "Silinemedi");
          showToast("Video silindi");
          void loadGalleryStats();
          refreshProducedAfterGalleryDelete();
        } catch (e) {
          showToast(e.message || "Silinemedi", 6000);
          void loadGallery({ soft: true });
        }
      });
    });
    bindGallerySelection(grid);
    bindGalleryCopyButtons(grid, galleryItemsCache);
    bindGalleryCardMedia(grid);
    if (!soft) {
      setTimeout(() => {
        if ($("view-gallery") && !$("view-gallery").hidden) {
          void backfillGalleryPublishPacks(items);
        }
      }, 8000);
    }
  } catch (e) {
    const msg =
      e?.name === "AbortError"
        ? "Galeri zaman asimi — sunucu meşgul olabilir. Biraz bekleyip Yenile deyin."
        : "Galeri yuklenemedi.";
    if (!soft) grid.innerHTML = `<p class="gallery-empty">${escapeHtml(msg)}</p>`;
  }
}

async function openLongformGalleryFolder(entryId) {
  const r = await fetch(`/api/gallery/longform/${encodeURIComponent(entryId)}/open-folder`, {
    method: "POST",
  });
  const data = await readApiJson(r).catch(() => ({}));
  if (!r.ok) {
    throw new Error(data.detail || data.message || "Klasor acilamadi");
  }
  showToast(data.folder_path ? `Klasor acildi` : "Klasor acildi");
  return data;
}

function setGalleryViewMode(mode) {
  galleryViewMode = mode === "long" ? "long" : "short";
  clearGallerySelection();
  $("gallery-tab-short")?.classList.toggle("active", galleryViewMode === "short");
  $("gallery-tab-long")?.classList.toggle("active", galleryViewMode === "long");
  $("gallery-tab-short")?.setAttribute("aria-selected", galleryViewMode === "short" ? "true" : "false");
  $("gallery-tab-long")?.setAttribute("aria-selected", galleryViewMode === "long" ? "true" : "false");
  if (galleryViewMode === "long") void loadLongformGallery();
  else void loadGallery();
}

function isLongformGalleryItem(item) {
  if (!item) return false;
  return !!(item.longform_id || item.per_chapter || item.chapter_count || item._galleryKind === "longform");
}

function longformGalleryMontageHtml(item) {
  const assets = item.assets || {};
  const chapters = assets.chapters || [];
  const clips = assets.clips || [];
  let html = "";

  if (chapters.length) {
    html += `<p class="hint">Her baslik kendi klasorunde: ses + altyazi (+ senaryo). Gorsel/video ortak <code>clips/</code> klasorunde.</p>`;
    const missing = chapters.filter((ch) => ch.missing_audio || (!ch.audio_tr_url && !ch.audio_en_url));
    if (missing.length) {
      html += `<p class="hint err">Eksik: ${missing.length} baslikta ses/altyazi yok — uretimde senaryo basarisiz olmus. «Tekrar dene» ile tamamlayin.</p>`;
    }
    html += `<div class="gallery-lf-chapters">`;
    chapters.forEach((ch, i) => {
      const label = escapeHtml(ch.display_title || ch.title || ch.slug || `Bolum ${i + 1}`);
      const n = Number(ch.index ?? i) + 1;
      const noAudio = !ch.audio_tr_url && !ch.audio_en_url;
      html += `<div class="gallery-lf-chapter${noAudio ? " gallery-lf-chapter-missing" : ""}">`;
      html += `<p class="gallery-lf-chapter-title"><span class="gallery-lf-chapter-num">${n}</span> ${label}</p>`;
      html += `<div class="btn-row btn-row-tight gallery-montage-actions">`;
      if (ch.audio_tr_url) {
        html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(ch.audio_tr_url)}" download>TR ses</a>`;
      }
      if (ch.subtitle_tr_url) {
        html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(ch.subtitle_tr_url)}" download>TR altyazi</a>`;
      }
      if (ch.script_tr_url) {
        html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(ch.script_tr_url)}" download>TR senaryo</a>`;
      }
      if (ch.audio_en_url) {
        html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(ch.audio_en_url)}" download>EN ses</a>`;
      }
      if (ch.subtitle_en_url) {
        html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(ch.subtitle_en_url)}" download>EN altyazi</a>`;
      }
      if (noAudio) {
        html += `<span class="hint err">Ses/altyazi yok (senaryo uretilemedi)</span>`;
      }
      html += `</div></div>`;
    });
    html += `</div>`;
  } else {
    html += `<div class="btn-row btn-row-tight gallery-montage-actions">`;
    if (assets.audio_url) {
      html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(assets.audio_url)}" download>TR ses</a>`;
    }
    if (assets.subtitle_url) {
      html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(assets.subtitle_url)}" download>TR altyazi</a>`;
    }
    if (assets.script_url) {
      html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(assets.script_url)}" download>TR senaryo</a>`;
    }
    if (assets.audio_en_url) {
      html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(assets.audio_en_url)}" download>EN ses</a>`;
    }
    if (assets.subtitle_en_url) {
      html += `<a class="btn-copy btn-sm gallery-montage-link" href="${escapeHtml(assets.subtitle_en_url)}" download>EN altyazi</a>`;
    }
    html += `</div>`;
  }

  if (clips.length) {
    html += `<p class="hint gallery-montage-clips-title">Ortak clips/ — ${clips.length} klip/gorsel</p>${galleryMontageClipsHtml(clips)}`;
  }
  return html;
}

function openLongformGalleryDetail(item, { skipWangpLoad = false } = {}) {
  galleryDetailItem = { ...item, _galleryKind: "longform" };
  const modal = $("gallery-detail-modal");
  const title = $("gallery-detail-title");
  const sub = $("gallery-detail-subtitle");
  const body = $("gallery-detail-body");
  if (!modal || !body) return;
  if (title) title.textContent = item.main_subject || item.title || "Uzun video";
  if (sub) {
    sub.textContent = `${item.chapter_count || 0} bolum · ${item.clip_count || 0} klip · ${formatDate(item.created_at)}`;
  }
  const chapters = (item.chapters || [])
    .map(
      (ch) =>
        `<li>${escapeHtml(String((ch.index ?? 0) + 1))}. ${escapeHtml(ch.display_title || ch.title || "")}</li>`
    )
    .join("");
  const titleText = galleryTitleText(item);
  const captionOnly = (item.caption || item.publish_pack?.best_caption || "").trim();
  const scriptText = (item.script || "").trim();
  const descCopy = galleryDescriptionText(item) || "—";
  const tagsText = galleryTagsText(item);
  const packing = publishPackNeedsGenerate(item);
  body.innerHTML = `
    <section class="gallery-detail-section">
      <h4>Yayin metinleri</h4>
      ${
        packing
          ? `<p class="hint">Baslik / aciklama / etiket LLM ile hazirlaniyor…</p>`
          : ""
      }
      <div class="gallery-copy-block">
        <div class="gallery-copy-row">
          <span class="gallery-copy-label">Baslik</span>
          <p class="gallery-copy-text" title="${escapeHtml(titleText)}">${escapeHtml(titleText)}</p>
          <div class="gallery-detail-btn-col">
            <button type="button" class="btn-copy btn-copy-row" data-copy-title="${item.id}">Kopyala</button>
            <button type="button" class="btn-ghost btn-sm btn-gallery-field-regen" data-regen-field="title">Degistir</button>
          </div>
        </div>
        <div class="gallery-copy-row gallery-copy-row-desc">
          <span class="gallery-copy-label">Aciklama</span>
          <div class="gallery-copy-stack">
            <p class="gallery-copy-text gallery-copy-desc-full">${escapeHtml(captionOnly || "—")}</p>
            ${
              scriptText
                ? `<p class="gallery-detail-desc-script-label">Senaryo</p>
            <p class="gallery-copy-text gallery-copy-script-full">${escapeHtml(scriptText)}</p>`
                : item.has_script
                  ? `<p class="hint">Senaryo yukleniyor…</p>`
                  : ""
            }
          </div>
          <div class="gallery-detail-btn-col">
            <button type="button" class="btn-copy btn-copy-row" data-copy-desc="${item.id}" ${descCopy === "—" ? "disabled" : ""}>Kopyala</button>
            <button type="button" class="btn-ghost btn-sm btn-gallery-field-regen" data-regen-field="description">Degistir</button>
          </div>
        </div>
        <div class="gallery-copy-row">
          <span class="gallery-copy-label">Etiket</span>
          <p class="gallery-copy-text gallery-copy-muted">${tagsText ? "Etiketler gizli — kopyalanabilir" : "—"}</p>
          <div class="gallery-detail-btn-col">
            <button type="button" class="btn-copy btn-copy-row" data-copy-tags="${item.id}" ${tagsText ? "" : "disabled"}>Kopyala</button>
            <button type="button" class="btn-ghost btn-sm btn-gallery-field-regen" data-regen-field="tags">Degistir</button>
          </div>
        </div>
      </div>
      <p class="hint">Aciklama kopyala = yayin metni + senaryo. Klasorde <code>baslik.txt</code>, <code>aciklama.txt</code>, <code>etiketler.txt</code>.</p>
    </section>
    <section class="gallery-detail-section">
      <h4>Montaj paketi</h4>
      <p class="hint">Klasor yapisi: <code>01-baslik/</code> (ses+altyazi) … + ortak <code>clips/</code></p>
      ${longformGalleryMontageHtml(item)}
      <div class="btn-row btn-row-tight">
        <button type="button" class="btn-primary btn-sm" id="btn-lf-open-folder">Klasoru ac</button>
      </div>
    </section>
    ${
      chapters
        ? `<section class="gallery-detail-section"><h4>Bolum plani</h4><ol class="longform-summary-list">${chapters}</ol></section>`
        : ""
    }
    ${galleryWangpSectionHtml(item)}
  `;
  bindGalleryCopyButtons(body, [item]);
  bindLongformGalleryWangpActions(item);
  $("btn-lf-open-folder")?.addEventListener("click", () => {
    void openLongformGalleryFolder(item.id).catch((e) => showToast(e.message, 5000));
  });
  modal.classList.remove("hidden");
  if (skipWangpLoad) return;
  if (packing) {
    void ensureGalleryPublishPack(item, { longform: true }).then(() =>
      loadLongformGalleryWangpIfNeeded(galleryDetailItem || item)
    );
  } else {
    void loadLongformGalleryWangpIfNeeded(item);
  }
}

async function loadLongformGallery() {
  const grid = $("gallery-grid");
  if (!grid) return;
  clearGallerySelection();
  grid.innerHTML = '<p class="gallery-empty">Yukleniyor...</p>';
  const plat = $("gallery-filter-platform")?.value || "";
  const niche = $("gallery-filter-niche")?.value || "";
  const qs = new URLSearchParams();
  if (plat) qs.set("platform", plat);
  if (niche) qs.set("niche", niche);
  try {
    const r = await fetchWithTimeout(`/api/gallery/longform?${qs.toString()}`, {}, 20000);
    if (!r.ok) {
      grid.innerHTML = `<p class="gallery-empty">Uzun video galerisi yuklenemedi (HTTP ${r.status}).</p>`;
      return;
    }
    const data = await readApiJson(r);
    const items = data.items || [];
    longformGalleryCache = items;
    if (!items.length) {
      grid.innerHTML =
        '<p class="gallery-empty">Henuz uzun video paketi yok. Uretim sekmesinden uzun video olustur.</p>';
      updateGalleryBulkUi();
      return;
    }
    grid.innerHTML = items
      .map((item) => {
        const pb = PLATFORM_BADGES[item.platform] || null;
        const badge = pb ? `<span class="platform-badge ${pb.cls}">${pb.label}</span>` : "";
        const titleText = galleryTitleText(item);
        return `
      <article class="gallery-card gallery-card-longform" data-gallery-id="${item.id}">
        <label class="gallery-check">
          <input type="checkbox" class="gallery-select" data-id="${item.id}" />
          <span>Sec</span>
        </label>
        <div class="longform-folder-icon" aria-hidden="true">📁</div>
        <div class="gallery-meta">
          ${badge}
          <span class="platform-badge lang-badge">Uzun video</span>
          <h3>${escapeHtml(item.main_subject || titleText || "Uzun video")}</h3>
          <time>${formatDate(item.created_at)} · ${item.size_mb || "?"} MB</time>
          <p class="hint">${item.chapter_count || 0} bolum · ${item.clip_count || 0} klip/gorsel</p>
          ${galleryCopyRowsHtml(item)}
          <div class="gallery-actions">
            <button type="button" class="btn-primary btn-sm" data-lf-open="${item.id}">Klasoru ac</button>
            <button type="button" class="btn-ghost btn-sm" data-lf-detail="${item.id}">Detaylar</button>
            <button type="button" class="danger btn-sm" data-lf-delete="${item.id}">Sil</button>
          </div>
        </div>
      </article>`;
      })
      .join("");
    grid.querySelectorAll("[data-lf-open]").forEach((btn) => {
      btn.addEventListener("click", () => {
        void openLongformGalleryFolder(btn.dataset.lfOpen).catch((e) => showToast(e.message, 5000));
      });
    });
    grid.querySelectorAll("[data-lf-detail]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = longformGalleryCache.find((x) => x.id === btn.dataset.lfDetail);
        if (item) openLongformGalleryDetail(item);
      });
    });
    grid.querySelectorAll("[data-lf-delete]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("Bu uzun video klasoru silinsin mi? Galeri ve export klasoru kalici olarak silinir.")) return;
        try {
          const r = await fetch(`/api/gallery/longform/${encodeURIComponent(btn.dataset.lfDelete)}`, {
            method: "DELETE",
          });
          if (!r.ok) {
            const err = await readApiJson(r).catch(() => ({}));
            throw new Error(err.detail || err.error || `HTTP ${r.status}`);
          }
          showToast("Uzun video silindi");
          void loadLongformGallery();
        } catch (e) {
          showToast(e.message || "Silinemedi — klasor baska programda acik olabilir", 5000);
        }
      });
    });
    bindGallerySelection(grid);
    bindGalleryCopyButtons(grid, longformGalleryCache);
    void backfillGalleryPublishPacks(items, { longform: true });
  } catch (e) {
    grid.innerHTML = `<p class="gallery-empty">Uzun video galerisi yuklenemedi.</p>`;
  }
}

function renderSettingsBlock(section, block) {
  if (!block) return;
  const inst = $(`settings-${section}-instructions`);
  if (inst) inst.textContent = block.instructions || "";
  const pathEl = $(`settings-${section}-path`);
  if (pathEl) pathEl.textContent = block.folder || block.folder_relative || "";
  const ex = $(`settings-${section}-example`);
  if (ex) {
    ex.textContent = block.example ? `Ornek: ${block.example}` : "";
    ex.classList.toggle("hidden", !block.example);
  }
  const count = $(`settings-${section}-count`);
  if (count) {
    const ready = block.count_ready ?? 0;
    const total = block.count_total ?? 0;
    count.textContent = total
      ? `${ready} kullanilabilir / ${total} toplam`
      : "Henuz dosya yok";
  }
  if (section === "bgm") fillUploadBgmCategories(block.categories || []);
  if (section === "outros") {
    const dl = $("upload-channel-list");
    if (dl) {
      dl.innerHTML = (block.items || [])
        .map((i) => `<option value="${escapeHtml(i.label)}"></option>`)
        .join("");
    }
  }
  const list = $(`settings-${section}-list`);
  if (!list) return;
  const items = block.items || [];
  if (!items.length) {
    list.innerHTML =
      '<li class="settings-file-empty">Henuz yok — yukarida Yukle ile ekle.</li>';
    return;
  }
  const del = (id, label) =>
    `<button type="button" class="btn-ghost btn-sm settings-file-del" data-delete-asset="${section}" data-id="${escapeHtml(id)}" data-label="${escapeHtml(label)}">Sil</button>`;
  list.innerHTML = items
    .map((item) => {
      const ready = item.ready;
      const statusCls = ready ? "settings-file-ok" : "settings-file-warn";
      const status = ready ? "Hazir" : item.note || "Eksik";
      if (section === "rvc") {
        const meta = [item.pth || "—", item.has_index ? "index" : ""].filter(Boolean).join(" · ");
        return `<li class="${statusCls}"><span class="settings-file-name">${escapeHtml(item.label || item.id)}</span><span class="settings-file-meta">${escapeHtml(meta)}</span><span class="settings-file-status">${escapeHtml(status)}</span>${del(item.folder_name || item.id, item.label || item.id)}</li>`;
      }
      if (section === "bgm") {
        return `<li class="${statusCls}"><span class="settings-file-name">${escapeHtml(item.label)}</span><span class="settings-file-meta">${escapeHtml(item.category_label || item.category || "")}</span><span class="settings-file-status">${escapeHtml(item.filename || "")}</span>${del(item.filename, item.label)}</li>`;
      }
      return `<li class="${statusCls}"><span class="settings-file-name">${escapeHtml(item.label)}</span><span class="settings-file-meta">${escapeHtml(item.file || "—")}</span><span class="settings-file-status">${escapeHtml(status)}</span>${del(item.id, item.label)}</li>`;
    })
    .join("");
}

function fillUploadBgmCategories(categories) {
  const sel = $("upload-bgm-category");
  if (!sel || !categories.length) return;
  const cur = sel.value || currentNicheId();
  sel.innerHTML = categories
    .map((c) => {
      const label = c.id === "ortak" ? "Ortak (tum nisler)" : c.label;
      return `<option value="${escapeHtml(c.id)}">${escapeHtml(label)} · ${c.track_count ?? 0}</option>`;
    })
    .join("");
  sel.value = categories.some((c) => c.id === cur) ? cur : categories[0].id;
  syncSelectUi(sel);
}

async function uploadSettingsFiles(kind, fileList, btn) {
  const files = [...(fileList || [])];
  if (!files.length) return;
  const section = kind === "intro" || kind === "outro" ? "outros" : kind;
  const fd = new FormData();
  fd.append("section", section);
  if (section === "bgm") fd.append("target", $("upload-bgm-category")?.value || "ortak");
  if (section === "outros") {
    const channel = ($("upload-channel-name")?.value || "").trim();
    if (!channel) {
      setStatus("Once kanal adini yaz", true);
      $("upload-channel-name")?.focus();
      return;
    }
    fd.append("target", channel);
    fd.append("kind", kind);
  }
  if (section === "rvc") {
    fd.append("target", ($("upload-rvc-name")?.value || "").trim());
    fd.append("pitch", String(parseInt($("upload-rvc-pitch")?.value || "0", 10) || 0));
  }
  files.forEach((f) => fd.append("files", f, f.name));
  const orig = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Yukleniyor…";
  }
  try {
    const r = await fetch("/api/settings/files/upload", { method: "POST", body: fd });
    const data = await readApiJson(r);
    if (!r.ok) throw new Error(data.detail || "Yukleme basarisiz");
    applySettingsRefreshData(data);
    if (section === "rvc") $("upload-rvc-name").value = "";
    showToast(`Eklendi: ${(data.saved || []).join(", ")} — Uretim sekmesinde hazir`);
  } catch (e) {
    setStatus(e.message || "Yukleme basarisiz", true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = orig || "Yukle";
    }
  }
}

async function deleteSettingsAsset(section, id, label) {
  if (!confirm(`"${label}" silinsin mi? Bu islem geri alinamaz.`)) return;
  try {
    const r = await fetch("/api/settings/files/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section, id }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw new Error(data.detail || "Silinemedi");
    applySettingsRefreshData(data);
    showToast(`Silindi: ${label}`);
  } catch (e) {
    setStatus(e.message || "Silinemedi", true);
  }
}

function applySettingsRefreshData(data) {
  if (!data || !appConfig) return;
  if (data.rvc_voices) {
    appConfig.rvc_voices = data.rvc_voices;
    populateRvcVoices();
    populateVcRvcVoices();
  }
  if (data.rvc_available !== undefined) appConfig.rvc_available = data.rvc_available;
  if (data.rvc_voices?.length) appConfig.rvc_available = true;
  if ((data.rvc_available !== undefined || data.rvc_voices) && appConfig.tts_engines?.length) {
    const rvcOk = !!(appConfig.rvc_available || (appConfig.rvc_voices || []).length);
    appConfig.tts_engines = appConfig.tts_engines.map((e) =>
      e.id === "rvc" ? { ...e, available: rvcOk } : e
    );
  }
  if (data.bgm_tracks) appConfig.bgm_tracks = data.bgm_tracks;
  if (data.bgm_categories) appConfig.bgm_categories = data.bgm_categories;
  if (data.outros) appConfig.outros = data.outros;
  if (data.tts_engines) {
    appConfig.tts_engines = data.tts_engines;
  }
  if (appConfig.tts_engines?.length) {
    renderTtsEngineOptions(appConfig.tts_engines, { preferred: $("tts-engine")?.value });
  }
  populateRvcVoices();
  populateBgmTracks(appConfig.bgm_tracks || []);
  populateOutros(appConfig.outros || []);
  updateBgmTrackVisibility();
  updateBgmNicheHint();
  if (data.rvc) renderSettingsBlock("rvc", data.rvc);
  if (data.bgm) renderSettingsBlock("bgm", data.bgm);
  if (data.outros_scan) renderSettingsBlock("outros", data.outros_scan);
}

async function loadSettingsSubpanel(tab) {
  const name = SETTINGS_SUBTABS.includes(tab) ? tab : "system";
  try {
    if (name === "system") {
      await loadSetupPanel();
      await loadBackupPanel();
      await loadLiveSystemPanel();
    } else if (name === "api") {
      const provSel = $("llm-api-provider");
      if (!_llmApiCache && appConfig?.llm_api?.provider && provSel) {
        provSel.value = appConfig.llm_api.provider;
        syncSelectUi(provSel);
        syncLlmApiProviderUi();
      }
      await loadLlmApiSettings();
      await loadStockApiSettings();
      await loadMinimaxH3Settings();
    } else if (name === "telegram") {
      await loadTelegramSettings();
    } else if (name === "hooks") {
      await loadHooksSettings();
    } else if (name === "files") {
      const r = await fetch("/api/settings/assets");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await readApiJson(r);
      if (data.rvc) renderSettingsBlock("rvc", data.rvc);
      if (data.bgm) renderSettingsBlock("bgm", data.bgm);
      if (data.outros) renderSettingsBlock("outros", data.outros);
    }
  } catch {
    showToast("Ayarlar yuklenemedi");
  }
}

async function loadSettingsAssets() {
  await loadSettingsSubpanel(activeSettingsSubTab());
}

function renderSetupChecks(container, checks) {
  if (!container || !checks) return;
  container.innerHTML = "";
  Object.values(checks).forEach((item) => {
    const li = document.createElement("li");
    li.className = item.ok ? "ok" : "bad";
    const hint = item.hint ? ` — ${item.hint}` : "";
    li.textContent = `${item.label}${hint}`;
    container.appendChild(li);
  });
}

function updateSetupHint(el, data) {
  if (!el || !data) return;
  if (data.pull_running) {
    el.textContent = data.pull_message || "Model indiriliyor…";
    return;
  }
  if (data.ready) {
    el.textContent = "Durum: Uretim icin hazir.";
    return;
  }
  el.textContent = "Durum: Eksik adimlar var — «Kurulumu tamamla» ile otomatik duzeltin.";
}

async function loadSetupPanel() {
  try {
    const r = await fetch("/api/setup/status");
    if (!r.ok) return;
    const data = await readApiJson(r);
    renderSetupChecks($("setup-check-list"), data.checks);
    updateSetupHint($("setup-status-hint"), data);
    return data;
  } catch {
    const el = $("setup-status-hint");
    if (el) el.textContent = "Durum: Kurulum bilgisi alinamadi.";
    return null;
  }
}

function renderBackupList(items) {
  const ul = $("backup-list");
  const hint = $("backup-status-hint");
  if (!ul) return;
  ul.innerHTML = "";
  if (!items?.length) {
    if (hint) hint.textContent = "Son yedek: henuz alinmadi.";
    return;
  }
  const latest = items[0];
  if (hint) {
    hint.textContent = `Son yedek: ${latest.filename} (${latest.size_human}) — ${latest.created_at || ""}`;
  }
  items.slice(0, 5).forEach((it) => {
    const li = document.createElement("li");
    li.textContent = `${it.filename} · ${it.size_human}`;
    ul.appendChild(li);
  });
}

async function loadBackupPanel() {
  try {
    const r = await fetch("/api/backup/list");
    if (!r.ok) return;
    const data = await readApiJson(r);
    renderBackupList(data.items || []);
  } catch {
    const hint = $("backup-status-hint");
    if (hint) hint.textContent = "Yedek listesi alinamadi.";
  }
}

async function createDataBackup(btn) {
  const run = async () => {
    const r = await fetch("/api/backup/create", { method: "POST" });
    const data = await readApiJson(r);
    if (!r.ok) throw new Error(data.detail || data.error || `HTTP ${r.status}`);
    showToast(`Yedek alindi: ${data.filename} (${data.size_human})`, 5000);
    await loadBackupPanel();
  };
  if (btn) {
    await runSettingsButton(btn, "Yedekleniyor…", run);
  } else {
    await run();
  }
}

async function openBackupFolder() {
  const r = await fetch("/api/backup/open-folder", { method: "POST" });
  if (!r.ok) {
    showToast("Klasor acilamadi", 4000);
    return;
  }
  await loadBackupPanel();
}

function renderLiveSystemRows(data) {
  const ul = $("live-system-list");
  const hint = $("live-system-updated");
  if (!ul || !data) return;
  ul.innerHTML = "";

  const rows = [];
  const gpuLive = data.gpu?.live || {};
  if (gpuLive.available) {
    const vram = gpuLive.memory_used_human || "?";
    const util = gpuLive.utilization_pct != null ? `, GPU %${gpuLive.utilization_pct}` : "";
    const temp = gpuLive.temperature_c != null ? `, ${gpuLive.temperature_c}°C` : "";
    rows.push({
      ok: true,
      label: "GPU / VRAM",
      hint: `${gpuLive.name || data.gpu?.gpu_name || "NVIDIA"} — ${vram}${util}${temp}`,
    });
  } else {
    rows.push({ ok: false, label: "GPU / VRAM", hint: "NVIDIA yok veya devre disi (CPU modu)" });
  }

  const disk = data.disk?.data || {};
  rows.push({
    ok: !!disk.ok,
    label: "Disk (data/)",
    hint: `bos ${disk.free_human || "?"} / ${disk.total_human || "?"}${disk.warning ? ` — ${disk.warning}` : ""}`,
  });

  const oll = data.ollama || {};
  const model = oll.model_name || oll.configured_model || "?";
  const loaded = oll.loaded_count || 0;
  const loadedHint =
    loaded > 0
      ? ` — VRAM'de ${loaded} model${loaded > 1 ? "" : ""}: ${(oll.loaded_models || []).map((m) => m.name).join(", ")}`
      : "";
  rows.push({
    ok: !!oll.running,
    label: "Ollama",
    hint: oll.running
      ? `${model}${loadedHint}`
      : oll.model_error || "calismiyor — ollama serve",
  });

  rows.push({
    ok: !!data.ffmpeg?.ok,
    label: "ffmpeg",
    hint: data.ffmpeg?.hint || "",
  });

  const engine = data.engine_api || {};
  rows.push({
    ok: !!engine.ok,
    label: "motor motor API",
    hint: engine.ok ? engine.url || "calisiyor" : engine.error || "calismiyor",
  });

  const q = data.queue || {};
  const qParts = [];
  if (q.processing) qParts.push("isleniyor");
  if (q.pending_count) qParts.push(`${q.pending_count} bekleyen`);
  if (q.current_label) qParts.push(`su an: ${q.current_label}`);
  rows.push({
    ok: true,
    label: "Uretim kuyrugu",
    hint: qParts.length ? qParts.join(" · ") : "bos",
  });

  const quota = data.stock_quota || {};
  const px = quota.pexels;
  if (data.pexels_configured) {
    if (px?.ok && px.remaining != null && px.limit != null) {
      rows.push({ ok: true, label: "Pexels kota", hint: `saatlik kalan ${px.remaining} / ${px.limit}` });
    } else {
      rows.push({
        ok: false,
        label: "Pexels kota",
        hint: px?.error || "test edilemedi",
      });
    }
  } else {
    rows.push({ ok: false, label: "Pexels API", hint: "anahtar tanimli degil" });
  }

  const pb = quota.pixabay;
  if (data.pixabay_configured) {
    rows.push({
      ok: pb?.ok !== false,
      label: "Pixabay",
      hint: pb?.ok ? "baglanti OK" : pb?.error || "test edilemedi",
    });
  } else {
    rows.push({ ok: false, label: "Pixabay API", hint: "anahtar tanimli degil" });
  }

  rows.forEach((item) => {
    const li = document.createElement("li");
    li.className = item.ok ? "ok" : "bad";
    const extra = item.hint ? ` — ${item.hint}` : "";
    li.textContent = `${item.label}${extra}`;
    ul.appendChild(li);
  });

  if (hint) {
    const ts = data.ts ? new Date(data.ts * 1000) : new Date();
    hint.textContent = `Son guncelleme: ${ts.toLocaleTimeString("tr-TR")}`;
  }
}

async function loadLiveSystemPanel() {
  try {
    const r = await fetch("/api/system/live");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await readApiJson(r);
    renderLiveSystemRows(data);
    return data;
  } catch {
    const hint = $("live-system-updated");
    if (hint) hint.textContent = "Canli sistem bilgisi alinamadi.";
    return null;
  }
}

let setupModalDismissed = false;
let setupAutoStarted = false;
let setupPollTimer = null;

function stopSetupPolling() {
  if (setupPollTimer) {
    clearInterval(setupPollTimer);
    setupPollTimer = null;
  }
}

async function pollSetupStatusWhileRunning() {
  try {
    const r = await fetch("/api/setup/status");
    if (!r.ok) return;
    const data = await readApiJson(r);
    renderSetupChecks($("setup-check-list"), data.checks);
    renderSetupChecks($("setup-modal-checks"), data.checks);
    updateSetupHint($("setup-status-hint"), data);
    updateSetupHint($("setup-modal-hint"), data);
    if (data.ready) {
      stopSetupPolling();
      showToast("Kurulum tamamlandi");
      hideSetupModal();
      await refreshOllamaStatus();
      await loadConfig(true);
      return;
    }
    if (!data.pull_running && !data.ready) {
      stopSetupPolling();
    }
  } catch {
    /* ignore transient errors while polling */
  }
}

function startSetupPolling() {
  stopSetupPolling();
  setupPollTimer = setInterval(() => void pollSetupStatusWhileRunning(), 2500);
}

async function maybeShowSetupModal() {
  if (setupModalDismissed) return;
  try {
    const r = await fetch("/api/setup/status");
    if (!r.ok) return;
    const data = await readApiJson(r);
    if (data.ready || data.setup_completed) return;
    const modal = $("setup-modal");
    if (!modal) return;
    renderSetupChecks($("setup-modal-checks"), data.checks);
    updateSetupHint($("setup-modal-hint"), data);
    modal.classList.remove("hidden");
    if (!setupAutoStarted) {
      setupAutoStarted = true;
      const hint = $("setup-modal-hint");
      if (hint) hint.textContent = "Ilk kurulum baslatiliyor — ffmpeg ve LLM modeli indirilebilir…";
      await runSetupWizard($("btn-setup-modal-run"), { auto: true });
    }
  } catch {
    /* ignore */
  }
}

function hideSetupModal() {
  $("setup-modal")?.classList.add("hidden");
}

async function runSetupWizard(btn, { auto = false } = {}) {
  const orig = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = auto ? "Ilk kurulum…" : "Calisiyor…";
  }
  try {
    const r = await fetch("/api/setup/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_ollama: true, pull_model: true, install_ffmpeg: true }),
    });
    const data = await readApiJson(r);
    renderSetupChecks($("setup-check-list"), data.checks);
    renderSetupChecks($("setup-modal-checks"), data.checks);
    updateSetupHint($("setup-status-hint"), data);
    updateSetupHint($("setup-modal-hint"), data);
    const msgs = (data.messages || []).join(" · ");
    if (data.ready) {
      showToast("Kurulum tamamlandi");
      hideSetupModal();
    } else if (data.pull_running) {
      showToast(msgs || "Model arka planda indiriliyor…", 5000);
      startSetupPolling();
    } else if (!auto) {
      showToast(msgs || "Kurulum eksik kaldi", 6000);
    }
    await refreshOllamaStatus();
    await loadConfig(true);
  } catch (e) {
    if (!auto) showToast(e.message || "Kurulum basarisiz", 5000);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = orig || "Kurulumu tamamla";
    }
  }
}

function updateStockApiStatusHint(data, { flash = "" } = {}) {
  const el = $("stock-api-status-hint");
  if (!el || !data) return;
  el.classList.remove("ok", "warn", "bad");
  if (!data.has_pexels_key && !data.has_pixabay_key) {
    el.textContent = "Durum: API anahtari yok — yukaridaki rehberle alip kaydedin.";
    el.classList.add("warn");
    return;
  }
  const parts = [];
  if (data.has_pexels_key) {
    parts.push(`Pexels: ${data.pexels_key_masked}${data.pexels_saved ? "" : " (ortam degiskeni)"}`);
  }
  if (data.has_pixabay_key) {
    parts.push(`Pixabay: ${data.pixabay_key_masked}${data.pixabay_saved ? "" : " (ortam degiskeni)"}`);
  }
  const prefix = flash ? `${flash} · ` : "Durum: ";
  el.textContent = `${prefix}${parts.join(" · ")}`;
  if (flash) el.classList.add("ok");
}

function formatQuotaReset(resetAt) {
  const ts = Number(resetAt);
  if (!ts) return "";
  const ms = ts > 1e12 ? ts : ts * 1000;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
}

function updateStockApiQuotaHint(quota) {
  const el = $("stock-api-quota-hint");
  if (!el) return;
  if (!quota) {
    el.textContent = "";
    el.classList.remove("ok", "warn", "bad");
    return;
  }
  const parts = [];
  const p = quota.pexels;
  if (p) {
    if (!p.ok) {
      parts.push(`Pexels kota: hata${p.error ? ` (${p.error})` : ""}`);
    } else if (p.remaining != null && p.limit != null) {
      let line = `Pexels kota: ${p.remaining} / ${p.limit} kaldi (saatlik)`;
      const reset = formatQuotaReset(p.reset_at);
      if (reset) line += ` · sifirlanma ~${reset}`;
      parts.push(line);
    } else if (p.remaining != null) {
      parts.push(`Pexels kota: ${p.remaining} istek kaldi`);
    }
  }
  const x = quota.pixabay;
  if (x) {
    if (!x.ok) {
      parts.push(`Pixabay: hata${x.error ? ` (${x.error})` : ""}`);
    } else {
      parts.push(`Pixabay: bagli · ~${x.limit_per_minute || 100} istek/dk limit`);
    }
  }
  if (!parts.length) {
    el.textContent = "";
    el.classList.remove("ok", "warn", "bad");
    return;
  }
  el.textContent = parts.join(" · ");
  el.classList.toggle("ok", !!(p?.ok || x?.ok));
  el.classList.toggle("warn", !!(p && !p.ok) || !!(x && !x.ok));
}

async function loadStockApiQuota() {
  try {
    const r = await fetch("/api/settings/stock-api/quota");
    if (!r.ok) return;
    updateStockApiQuotaHint(await readApiJson(r));
  } catch {
    const el = $("stock-api-quota-hint");
    if (el) el.textContent = "";
  }
}

async function loadStockApiSettings() {
  try {
    const r = await fetch("/api/settings/stock-api");
    if (!r.ok) return;
    const data = await readApiJson(r);
    const p = $("stock-api-pexels");
    const x = $("stock-api-pixabay");
    if (p) {
      p.value = "";
      p.placeholder = data.has_pexels_key
        ? `Kayitli: ${data.pexels_key_masked}`
        : "Pexels API key";
    }
    if (x) {
      x.value = "";
      x.placeholder = data.has_pixabay_key
        ? `Kayitli: ${data.pixabay_key_masked}`
        : "Pixabay API key";
    }
    updateStockApiStatusHint(data);
    void loadStockApiQuota();
  } catch {
    const el = $("stock-api-status-hint");
    if (el) el.textContent = "Durum: API ayarlari yuklenemedi.";
  }
}

const LLM_API_MODEL_KEYS = {
  openai: { models: "openai_models", model: "openai_model" },
  nvidia: { models: "nvidia_models", model: "nvidia_model" },
  gemini: { models: "gemini_models", model: "gemini_model" },
  grok: { models: "grok_models", model: "grok_model" },
  claude: { models: "claude_models", model: "claude_model" },
};

let _llmApiCache = null;

function syncLlmApiProviderUi() {
  const prov = ($("llm-api-provider")?.value || "ollama").trim();
  const modelWrap = $("llm-api-model-wrap");
  const modelSel = $("llm-api-model");
  const keysGrid = $("llm-api-keys-grid");
  if (modelWrap) modelWrap.hidden = prov === "ollama";
  if (keysGrid) {
    keysGrid.querySelectorAll("[data-llm-key]").forEach((el) => {
      el.hidden = el.getAttribute("data-llm-key") !== prov;
    });
  }
  if (!modelSel || prov === "ollama") return;
  const meta = LLM_API_MODEL_KEYS[prov];
  if (!meta) return;
  const cache = _llmApiCache || appConfig?.llm_api || {};
  fillLlmApiModelSelect(prov, cache[meta.models] || [], cache[meta.model] || "");
  void refreshLlmApiModels(prov);
}

function fillLlmApiModelSelect(prov, list, current) {
  const modelSel = $("llm-api-model");
  if (!modelSel) return;
  const keep = (modelSel.dataset.provider === prov && modelSel.value) || current;
  modelSel.dataset.provider = prov;
  const ids = [...list];
  if (keep && !ids.includes(keep)) ids.unshift(keep);
  modelSel.innerHTML = ids.length
    ? ids.map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join("")
    : `<option value="">Model listesi bos — anahtari gir</option>`;
  modelSel.value = ids.includes(keep) ? keep : ids[0] || "";
  syncSelectUi(modelSel);
}

let _llmModelsReq = 0;

async function refreshLlmApiModels(prov) {
  const meta = LLM_API_MODEL_KEYS[prov];
  if (!meta) return;
  const reqId = ++_llmModelsReq;
  const typedKey = ($(`llm-api-${prov}-key`)?.value || "").trim();
  const hint = $("llm-api-status-hint");
  if (hint) hint.textContent = "Durum: modeller anahtardan cekiliyor…";
  let data = null;
  try {
    const r = await fetch("/api/settings/llm/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: prov, api_key: typedKey || null }),
    });
    data = r.ok ? await readApiJson(r) : null;
  } catch {
    data = null;
  }
  if (reqId !== _llmModelsReq || ($("llm-api-provider")?.value || "") !== prov) return;
  if (!data) {
    setLlmApiStatusHint(_llmApiCache || { provider: prov }, "model listesi alinamadi");
    return;
  }
  if (_llmApiCache) _llmApiCache[meta.models] = data.models || [];
  fillLlmApiModelSelect(prov, data.models || [], data.current || "");
  const n = (data.models || []).length;
  const extra = data.ok
    ? `${n} model (anahtardan)`
    : `${data.detail || "liste alinamadi"} — ${data.source === "cache" ? "son liste" : "varsayilan liste"}`;
  setLlmApiStatusHint(_llmApiCache || { provider: prov }, extra);
  if (data.writer_models?.length) {
    appConfig.llm_writer_models = data.writer_models;
    fillWriterModelSelect(data.writer_models, currentWriterModel());
  }
}

function setLlmApiStatusHint(data, extra) {
  const el = $("llm-api-status-hint");
  if (!el) return;
  const p = data?.provider || "ollama";
  const bits = [`Saglayici: ${p}`];
  if (p !== "ollama") {
    const setKey = `${p}_api_key_set`;
    bits.push(data?.[setKey] ? "anahtar kayitli" : "anahtar yok");
    const masked = data?.[`${p}_api_key_masked`];
    if (masked) bits.push(masked);
  } else {
    bits.push("yerel Ollama");
  }
  if (extra) bits.push(extra);
  el.textContent = `Durum: ${bits.join(" · ")}`;
}

async function loadLlmApiSettings() {
  try {
    const r = await fetch("/api/settings/llm");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await readApiJson(r);
    _llmApiCache = data;
    const sel = $("llm-api-provider");
    if (sel) sel.value = data.provider || "ollama";
    const fill = (id, setFlag, masked) => {
      const inp = $(id);
      if (!inp) return;
      inp.value = "";
      inp.placeholder = setFlag ? `Kayitli: ${masked || "••••"}` : inp.placeholder;
    };
    fill("llm-api-openai-key", data.openai_api_key_set, data.openai_api_key_masked);
    fill("llm-api-nvidia-key", data.nvidia_api_key_set, data.nvidia_api_key_masked);
    fill("llm-api-gemini-key", data.gemini_api_key_set, data.gemini_api_key_masked);
    fill("llm-api-grok-key", data.grok_api_key_set, data.grok_api_key_masked);
    fill("llm-api-claude-key", data.claude_api_key_set, data.claude_api_key_masked);
    syncLlmApiProviderUi();
    setLlmApiStatusHint(data);
  } catch {
    const el = $("llm-api-status-hint");
    if (el) el.textContent = "Durum: yuklenemedi";
  }
}

async function saveLlmApiSettings() {
  const provider = ($("llm-api-provider")?.value || "ollama").trim();
  const body = { provider };
  const keyMap = {
    openai: "llm-api-openai-key",
    nvidia: "llm-api-nvidia-key",
    gemini: "llm-api-gemini-key",
    grok: "llm-api-grok-key",
    claude: "llm-api-claude-key",
  };
  for (const [p, id] of Object.entries(keyMap)) {
    const v = ($(id)?.value || "").trim();
    if (v) body[`${p}_api_key`] = v;
  }
  const meta = LLM_API_MODEL_KEYS[provider];
  if (meta) {
    const m = ($("llm-api-model")?.value || "").trim();
    if (m) body[meta.model] = m;
  }
  const r = await fetch("/api/settings/llm", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await readApiError(r));
  const saved = await readApiJson(r);
  applyLlmApiFromConfig(saved);
  await loadLlmApiSettings();
  if (saved.provider && saved.provider !== "ollama") {
    const mid = saved.active_model || saved.llm_default_writer || "";
    if (mid) localStorage.setItem(WRITER_KEY, mid);
    fillWriterModelSelect(
      saved.llm_writer_models || saved.writer_models || [],
      mid
    );
  } else {
    localStorage.removeItem(WRITER_KEY);
    // Ollama'ya donunce kurulu modelleri yeniden cek
    try {
      const cr = await fetch("/api/config");
      if (cr.ok) {
        const cfg = await readApiJson(cr);
        appConfig = { ...appConfig, ...cfg };
        fillWriterModelSelect(cfg.llm_writer_models || [], cfg.llm_default_writer || "");
      }
    } catch {
      fillWriterModelSelect([], "");
    }
  }
  updateOllamaPill();
  updateGenerateButton();
  showToast(
    saved.provider === "ollama"
      ? "LLM: Ollama (yerel)"
      : `LLM: ${saved.provider} · ${saved.active_model || "model"}`
  );
}

async function testLlmApiSettings() {
  const r = await fetch("/api/settings/llm/test", { method: "POST" });
  let data = {};
  try {
    data = await readApiJson(r);
  } catch {
    data = {};
  }
  if (!r.ok || !data.ok) {
    throw new Error(data.detail || "Test basarisiz");
  }
  setLlmApiStatusHint(_llmApiCache || { provider: data.provider }, `test OK (${data.model || ""})`);
  showToast(`LLM test OK — ${data.provider} · ${data.model || ""}`);
}

function setMinimaxH3StatusHint(data) {
  const el = $("minimax-h3-status-hint");
  if (!el) return;
  const h = data?.health || {};
  const bits = [
    data?.enabled ? "varsayilan otomatik acik" : "varsayilan kapali",
    data?.base_url || "",
  ];
  if (h.ok) bits.push("Studio+Comfy hazir");
  else if (h.online) bits.push(h.detail || "Comfy kapali");
  else bits.push(h.detail || "Studio kapali");
  el.textContent = `Durum: ${bits.filter(Boolean).join(" · ")}`;
}

async function loadMinimaxH3Settings() {
  try {
    const r = await fetch("/api/settings/minimax-h3");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await readApiJson(r);
    if ($("minimax-h3-enabled")) $("minimax-h3-enabled").checked = !!data.enabled;
    if ($("minimax-h3-auto-start")) $("minimax-h3-auto-start").checked = data.auto_start !== false;
    if ($("minimax-h3-url")) $("minimax-h3-url").value = data.base_url || "http://127.0.0.1:8787";
    if ($("minimax-h3-quality") && data.quality) $("minimax-h3-quality").value = String(data.quality);
    if ($("ai-visual-auto-minimax") && data.enabled) {
      $("ai-visual-auto-minimax").checked = true;
    }
    setMinimaxH3StatusHint(data);
  } catch {
    const el = $("minimax-h3-status-hint");
    if (el) el.textContent = "Durum: yuklenemedi";
  }
}

async function saveMinimaxH3Settings() {
  const body = {
    enabled: !!$("minimax-h3-enabled")?.checked,
    auto_start: !!$("minimax-h3-auto-start")?.checked,
    base_url: ($("minimax-h3-url")?.value || "").trim() || "http://127.0.0.1:8787",
    quality: ($("minimax-h3-quality")?.value || "736").trim(),
  };
  const r = await fetch("/api/settings/minimax-h3", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await readApiError(r));
  const data = await readApiJson(r);
  if ($("minimax-h3-url") && data.base_url) $("minimax-h3-url").value = data.base_url;
  setMinimaxH3StatusHint(data);
  if ($("ai-visual-auto-minimax")) $("ai-visual-auto-minimax").checked = !!data.enabled;
  showToast("H3 Studio ayarlari kaydedildi");
}

async function testMinimaxH3Settings() {
  const r = await fetch("/api/settings/minimax-h3/test", { method: "POST" });
  const data = await readApiJson(r).catch(() => ({}));
  if (!r.ok || !data.ok) {
    throw new Error(data.detail || "H3 Studio / Comfy yanit vermiyor");
  }
  if ($("minimax-h3-url") && data.base_url) $("minimax-h3-url").value = data.base_url;
  setMinimaxH3StatusHint({ ...(await fetch("/api/settings/minimax-h3").then((x) => readApiJson(x)).catch(() => ({}))), health: data });
  showToast("H3 Studio + Comfy hazir");
}

async function startMinimaxH3Studio() {
  showToast("H3 Studio baslatiliyor… (Comfy aciliyorsa birkaç dk)", 6000);
  const r = await fetch("/api/settings/minimax-h3/start", { method: "POST" });
  const data = await readApiJson(r).catch(() => ({}));
  if (!r.ok || !data.ok) {
    throw new Error(data.detail || "Studio baslatilamadi");
  }
  if ($("minimax-h3-url") && data.base_url) $("minimax-h3-url").value = data.base_url;
  setMinimaxH3StatusHint(data);
  showToast(`H3 Studio hazir · ${data.base_url || ""}`);
}

function populateHooksNicheSelect(selected) {
  const sel = $("hooks-niche-select");
  if (!sel) return;
  const niches = appConfig?.niches || [];
  if (!niches.length) {
    sel.innerHTML = `<option value="tarih_gizem">Tarih &amp; Gizem</option>`;
    syncSelectUi(sel);
    return;
  }
  sel.innerHTML = niches
    .map((n) => `<option value="${escapeHtml(n.id)}">${escapeHtml(n.label)}</option>`)
    .join("");
  if (selected && niches.some((n) => n.id === selected)) sel.value = selected;
  else if ($("niche")?.value && niches.some((n) => n.id === $("niche").value)) {
    sel.value = $("niche").value;
  }
  syncSelectUi(sel);
}

function currentHooksNiche() {
  return $("hooks-niche-select")?.value || $("niche")?.value || "tarih_gizem";
}

function renderHooksExamples(examples) {
  const list = $("hooks-examples-list");
  if (!list) return;
  const items = examples || [];
  if (!items.length) {
    list.innerHTML = `<li class="hint">Henuz ornek yok — <strong>+ Ekle</strong> ile acilis cumlesi ekleyin.</li>`;
    return;
  }
  list.innerHTML = items
    .map((item) => {
      const builtin = item.builtin ? ' <span class="hooks-tag">varsayilan</span>' : "";
      const id = escapeHtml(item.id || "");
      const raw = (item.text || "").trim();
      const text = escapeHtml(raw);
      const actions = item.builtin
        ? `<div class="hooks-item-actions">
            <button type="button" class="btn-ghost btn-sm btn-hooks-rate-good" data-id="${id}" data-text="${text}">Iyi</button>
            <button type="button" class="btn-ghost btn-sm btn-hooks-rate-bad" data-id="${id}" data-text="${text}">Kotu</button>
          </div>`
        : `<div class="hooks-item-actions">
            <button type="button" class="btn-ghost btn-sm btn-hooks-rate-good" data-id="${id}" data-text="${text}">Iyi</button>
            <button type="button" class="btn-ghost btn-sm btn-hooks-rate-bad" data-id="${id}" data-text="${text}">Kotu</button>
            <button type="button" class="btn-ghost btn-sm danger-text btn-hooks-del" data-id="${id}">Sil</button>
          </div>`;
      return `<li class="hooks-item" data-hook-id="${id}"><p class="hooks-item-text">${text}${builtin}</p>${actions}</li>`;
    })
    .join("");
  list.querySelectorAll(".btn-hooks-del").forEach((btn) => {
    btn.addEventListener("click", () => void deleteHookExample(btn.dataset.id));
  });
  list.querySelectorAll(".btn-hooks-rate-good").forEach((btn) => {
    btn.addEventListener("click", () => void rateHookExample(btn.dataset.id, btn.dataset.text, "good", btn));
  });
  list.querySelectorAll(".btn-hooks-rate-bad").forEach((btn) => {
    btn.addEventListener("click", () => void rateHookExample(btn.dataset.id, btn.dataset.text, "bad", btn));
  });
}

function renderHooksMemory(memory) {
  const goodEl = $("hooks-memory-good");
  const badEl = $("hooks-memory-bad");
  const good = memory?.good || [];
  const bad = memory?.bad || [];
  const rowHtml = (items, rating) => {
    if (!items.length) return `<li class="hint">Bos</li>`;
    return items
      .map((item) => {
        const src = item.source === "auto" ? ' <span class="hooks-tag">oto</span>' : "";
        const topic = item.topic
          ? `<span class="hooks-item-meta">${escapeHtml(item.topic)}</span>`
          : "";
        return `<li class="hooks-item hooks-memory-item">
          <p class="hooks-item-text">${escapeHtml(item.text || "")}${src}</p>
          ${topic}
          <button type="button" class="btn-ghost btn-sm danger-text btn-hooks-mem-del" data-id="${escapeHtml(item.id)}" data-rating="${rating}">Sil</button>
        </li>`;
      })
      .join("");
  };
  if (goodEl) goodEl.innerHTML = rowHtml(good, "good");
  if (badEl) badEl.innerHTML = rowHtml(bad, "bad");
  document.querySelectorAll(".btn-hooks-mem-del").forEach((btn) => {
    btn.addEventListener("click", () => void deleteHookMemory(btn.dataset.id, btn.dataset.rating));
  });
}

function openHooksCompose() {
  $("hooks-compose-form")?.classList.remove("hidden");
  $("btn-hooks-compose-open")?.classList.add("hidden");
  const ta = $("hooks-new-text");
  if (ta) {
    ta.focus();
  }
}

function closeHooksCompose(clear = true) {
  $("hooks-compose-form")?.classList.add("hidden");
  $("btn-hooks-compose-open")?.classList.remove("hidden");
  if (clear) {
    const ta = $("hooks-new-text");
    if (ta) ta.value = "";
  }
}

async function loadHooksSettings() {
  const niche = currentHooksNiche();
  populateHooksNicheSelect(niche);
  const hint = $("hooks-status-hint");
  if (hint) hint.textContent = "Yukleniyor…";
  try {
    const r = await fetch(`/api/settings/hooks?niche=${encodeURIComponent(niche)}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await readApiJson(r);
    renderHooksExamples(data.examples || []);
    renderHooksMemory(data.memory || {});
    if (hint) {
      const g = (data.memory?.good || []).length;
      const b = (data.memory?.bad || []).length;
      hint.textContent = `${(data.examples || []).length} ornek · hafiza: ${g} iyi, ${b} kotu`;
    }
    initCustomSelects($("settings-panel-hooks"));
    refreshAllCustomSelects();
  } catch (e) {
    if (hint) hint.textContent = "Hook ayarlari yuklenemedi.";
    showToast(e.message || "Hook ayarlari yuklenemedi", 5000);
  }
}

async function saveHookExample() {
  const text = ($("hooks-new-text")?.value || "").trim();
  if (text.length < 8) {
    showToast("Hook en az 8 karakter olmali", 4000);
    $("hooks-new-text")?.focus();
    return;
  }
  const btn = $("btn-hooks-save");
  const niche = currentHooksNiche();
  if (btn) btn.disabled = true;
  try {
    const r = await fetch("/api/settings/hooks/examples", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ niche, text }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Kaydedilemedi");
    closeHooksCompose(true);
    renderHooksExamples(data.examples || []);
    const hint = $("hooks-status-hint");
    if (hint) {
      hint.textContent = `Kaydedildi · ${(data.examples || []).length} ornek`;
      hint.classList.add("ok");
      window.setTimeout(() => {
        hint.classList.remove("ok");
        void loadHooksSettings();
      }, 5000);
    }
    showToast("Hook kaydedildi ve listeye eklendi", 4500);
  } catch (e) {
    showToast(e.message || "Hook kaydedilemedi", 5000);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function deleteHookExample(exampleId) {
  if (!exampleId) return;
  const niche = currentHooksNiche();
  try {
    const r = await fetch(
      `/api/settings/hooks/examples/${encodeURIComponent(exampleId)}?niche=${encodeURIComponent(niche)}`,
      { method: "DELETE" }
    );
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Silinemedi");
    renderHooksExamples(data.examples || []);
    showToast("Hook silindi");
    void loadHooksSettings();
  } catch (e) {
    showToast(e.message || "Silinemedi", 5000);
  }
}

async function rateHookExample(exampleId, text, rating, btn) {
  const hook = (text || "").trim();
  if (hook.length < 8) return;
  const niche = currentHooksNiche();
  const row = btn?.closest(".hooks-item");
  const actions = row?.querySelector(".hooks-item-actions");
  if (actions) actions.innerHTML = `<span class="hint">Yeni hook uretiliyor…</span>`;
  try {
    const r = await fetch("/api/settings/hooks/rate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ niche, example_id: exampleId || "", text: hook, rating }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Islem basarisiz");
    renderHooksExamples(data.examples || []);
    renderHooksMemory(data.memory || {});
    const hint = $("hooks-status-hint");
    if (hint) {
      const g = (data.memory?.good || []).length;
      const b = (data.memory?.bad || []).length;
      hint.textContent = `${rating === "good" ? "Iyi" : "Kotu"} kaydedildi · ${(data.examples || []).length} ornek · hafiza: ${g} iyi, ${b} kotu`;
      hint.classList.add("ok");
      window.setTimeout(() => hint.classList.remove("ok"), 6000);
    }
    if (data.generated?.text) {
      showToast(
        `${rating === "good" ? "Iyi" : "Kotu"} listeye alindi · yerine yeni hook eklendi`,
        5000
      );
    } else if (data.warning) {
      showToast(`${rating === "good" ? "Iyi" : "Kotu"} kaydedildi · yeni hook uretilemedi: ${data.warning}`, 6000);
    } else {
      showToast(`${rating === "good" ? "Iyi" : "Kotu"} kaydedildi`, 4000);
    }
  } catch (e) {
    showToast(e.message || "Hook islenemedi", 5000);
    void loadHooksSettings();
  }
}

async function addHookMemory(text, rating) {
  const hook = (text || "").trim();
  if (hook.length < 8) return;
  const niche = currentHooksNiche();
  try {
    const r = await fetch("/api/settings/hooks/memory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ niche, text: hook, rating }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Hafizaya eklenemedi");
    renderHooksMemory(data.memory || {});
    showToast(rating === "good" ? "Iyi hook hafizaya eklendi" : "Kotu hook hafizaya eklendi");
    void loadHooksSettings();
  } catch (e) {
    showToast(e.message || "Hafizaya eklenemedi", 5000);
  }
}

async function deleteHookMemory(entryId, rating) {
  if (!entryId) return;
  const niche = currentHooksNiche();
  try {
    const r = await fetch(
      `/api/settings/hooks/memory/${encodeURIComponent(entryId)}?niche=${encodeURIComponent(niche)}&rating=${encodeURIComponent(rating || "good")}`,
      { method: "DELETE" }
    );
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Silinemedi");
    renderHooksMemory(data.memory || {});
    showToast("Hafiza kaydi silindi");
    void loadHooksSettings();
  } catch (e) {
    showToast(e.message || "Silinemedi", 5000);
  }
}

async function saveStockApiSettings() {
  const body = {};
  const p = ($("stock-api-pexels")?.value || "").trim();
  const x = ($("stock-api-pixabay")?.value || "").trim();
  if (!p && !x) {
    showToast("Kaydetmek icin en az bir API anahtari girin", 4000);
    return;
  }
  if (p) body.pexels_key = p;
  if (x) body.pixabay_key = x;
  const r = await fetch("/api/settings/stock-api", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, "API anahtarlari kaydedilemedi");
  if ($("stock-api-pexels")) $("stock-api-pexels").value = "";
  if ($("stock-api-pixabay")) $("stock-api-pixabay").value = "";
  updateStockApiStatusHint(data, { flash: "Kaydedildi" });
  showToast("Stok API anahtarlari kaydedildi", 4500);
  try {
    await loadConfig(true);
  } catch {
    /* kayit tamam; config yenileme istege bagli */
  }
  void loadStockApiQuota();
  window.setTimeout(() => updateStockApiStatusHint(data), 8000);
}

async function testStockApiSettings() {
  const body = {};
  const p = ($("stock-api-pexels")?.value || "").trim();
  const x = ($("stock-api-pixabay")?.value || "").trim();
  if (p) body.pexels_key = p;
  if (x) body.pixabay_key = x;
  const r = await fetch("/api/settings/stock-api/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, "API testi basarisiz");
  const pOk = data.pexels?.ok;
  const xOk = data.pixabay?.ok;
  showToast(
    `Pexels: ${pOk ? "OK" : data.pexels?.error || "hata"} · Pixabay: ${xOk ? "OK" : data.pixabay?.error || "hata"}`,
    5000
  );
  void loadStockApiQuota();
}

function updateTelegramGuideBotLink(data) {
  const link = $("telegram-guide-bot-link");
  if (!link) return;
  const bot = (data?.bot_username || "AkiFactory_bot").replace(/^@/, "");
  link.href = `https://t.me/${bot}`;
  link.textContent = `@${bot}`;
}

function updateTelegramUi(data) {
  updateTelegramGuideBotLink(data);
  updateTelegramStatusHint(data);
  const testBtn = $("btn-telegram-test");
  const ready = !!(data?.configured || (data?.has_token && data?.chat_id));
  if (testBtn) testBtn.disabled = !ready;

  const openBtn = $("btn-telegram-open-bot");
  const bot = (data?.bot_username || "AkiFactory_bot").replace(/^@/, "");
  if (openBtn) {
    openBtn.href = `https://t.me/${bot}`;
    openBtn.classList.remove("hidden");
  }

  const actionHint = $("telegram-action-hint");
  if (actionHint && data) {
    if (data.configured) {
      actionHint.textContent = "Baglanti hazir — istege bagli Test gonder.";
    } else if (data.has_token && !data.chat_id) {
      actionHint.textContent = "Token kayitli — bota /start yazip «Chat ID bul».";
    } else if (!data.has_token) {
      actionHint.textContent = "Token yapistir → Kaydet → bota /start → Chat ID bul.";
    } else {
      actionHint.textContent = "Once Kaydet, sonra Chat ID bul.";
    }
  }
}

async function runSettingsButton(btn, loadingText, fn) {
  if (!btn || btn.disabled) return;
  const orig = btn.textContent;
  btn.disabled = true;
  if (loadingText) btn.textContent = loadingText;
  try {
    return await fn();
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
    try {
      const r = await fetch("/api/telegram/settings");
      if (r.ok) updateTelegramUi(await readApiJson(r));
    } catch {
      /* ignore */
    }
  }
}

function updateTelegramStatusHint(data) {
  const el = $("telegram-status-hint");
  if (!el || !data) return;
  el.classList.remove("ok", "warn", "bad");
  if (!data.enabled) {
    el.textContent = "Durum: Bildirimler kapali.";
    el.classList.add("warn");
    return;
  }
  if (!data.has_token) {
    el.textContent = "Durum: Bot token girilmedi — paylasilan bot veya kendi BotFather token'i.";
    el.classList.add("warn");
    return;
  }
  const bot = data.bot_username ? `@${data.bot_username}` : "@AkiFactory_bot";
  if (!data.chat_id) {
    el.textContent = `Durum: Token kayitli (${data.bot_token_masked}). ${bot} → /start → Chat ID bul.`;
    el.classList.add("warn");
    return;
  }
  if (data.configured) {
    el.textContent = `Durum: Hazir · Chat ${data.chat_id} · ${bot}`;
    el.classList.add("ok");
    return;
  }
  el.textContent = `Durum: Chat ${data.chat_id} — Kaydet ile tamamla.`;
  el.classList.add("warn");
}

async function loadTelegramSettings() {
  try {
    const r = await fetch("/api/telegram/settings");
    if (!r.ok) return;
    const data = await readApiJson(r);
    if ($("telegram-enabled")) $("telegram-enabled").checked = data.enabled !== false;
    if ($("telegram-notify-video")) $("telegram-notify-video").checked = data.notify_video !== false;
    if ($("telegram-notify-queue")) $("telegram-notify-queue").checked = data.notify_queue !== false;
    if ($("telegram-chat-id")) $("telegram-chat-id").value = data.chat_id || "";
    const tok = $("telegram-bot-token");
    if (tok) {
      tok.value = "";
      tok.placeholder = data.has_token
        ? `Kayitli: ${data.bot_token_masked} (degistirmek icin yeni token)`
        : "Paylasilan veya BotFather token";
    }
    updateTelegramUi(data);
  } catch {
    const el = $("telegram-status-hint");
    if (el) {
      el.textContent = "Durum: Telegram ayarlari yuklenemedi.";
      el.classList.add("bad");
    }
  }
}

async function saveTelegramSettings() {
  const body = {
    enabled: !!$("telegram-enabled")?.checked,
    notify_video: !!$("telegram-notify-video")?.checked,
    notify_queue: !!$("telegram-notify-queue")?.checked,
    chat_id: ($("telegram-chat-id")?.value || "").trim() || null,
  };
  const token = ($("telegram-bot-token")?.value || "").trim();
  if (token) body.bot_token = token;
  const r = await fetch("/api/telegram/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, "Telegram ayarlari kaydedilemedi");
  if ($("telegram-bot-token")) $("telegram-bot-token").value = "";
  updateTelegramUi(data);
  showToast("Telegram ayarlari kaydedildi");
  return data;
}

async function discoverTelegramChat() {
  const token = ($("telegram-bot-token")?.value || "").trim();
  if (token) {
    await saveTelegramSettings();
  }
  const r = await fetch("/api/telegram/discover-chat", { method: "POST" });
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, "Chat ID bulunamadi");
  if ($("telegram-chat-id")) $("telegram-chat-id").value = data.chat_id || "";
  updateTelegramUi(data);
  showToast(`Chat ID bulundu: ${data.chat_id}`);
}

async function testTelegramNotification() {
  const chatId = ($("telegram-chat-id")?.value || "").trim();
  const token = ($("telegram-bot-token")?.value || "").trim();
  if (token || chatId) {
    await saveTelegramSettings();
  }
  const r = await fetch("/api/telegram/test", { method: "POST" });
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, "Test mesaji gonderilemedi");
  showToast("Telegram test mesaji gonderildi");
}

async function refreshSettingsSection(section, btn) {
  const orig = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Kontrol...";
  }
  try {
    const r = await fetch("/api/settings/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw new Error(data.detail || data.error || "Basarisiz");
    applySettingsRefreshData(data);
    const labels = { rvc: "RVC", bgm: "Muzik", outros: "Intro / outro", all: "Tum dosyalar" };
    showToast(`${labels[section] || section} guncellendi — Uretim sekmesinde kullanilabilir`);
  } catch (e) {
    setStatus(e.message || "Kontrol basarisiz", true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = orig || "Kontrol et";
    }
  }
}

async function openSettingsFolder(section) {
  try {
    if (window.akifactory?.openAssetsFolder) {
      const r = await window.akifactory.openAssetsFolder(section);
      if (!r?.ok) throw new Error(r?.error || "Acilamadi");
      showToast("Klasor acildi");
      return;
    }
    if (window.pywebview?.api?.open_assets_folder) {
      const r = await window.pywebview.api.open_assets_folder(section);
      if (!r?.ok) throw new Error(r?.error || "Acilamadi");
      showToast("Klasor acildi");
      return;
    }
    const r = await fetch("/api/settings/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ section }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw new Error(data.detail || "Acilamadi");
    showToast("Klasor acildi");
  } catch (e) {
    setStatus(e.message || "Klasor acilamadi", true);
  }
}

async function loadHistory() {
  const list = $("history-list");
  if (!list) return;
  const filter = $("history-filter")?.value || "all";
  try {
    const r = await fetch("/api/history");
    const data = await readApiJson(r);
    let items = data.items || [];
    if (filter === "fav") items = items.filter((h) => h.is_favorite);
    items.sort((a, b) => (b.is_favorite ? 1 : 0) - (a.is_favorite ? 1 : 0));
    const dl = $("history-datalist");
    if (dl) {
      dl.innerHTML = items
        .slice(0, 20)
        .map((h) => `<option value="${escapeHtml(h.topic)}"></option>`)
        .join("");
    }
    if (!items.length) {
      list.innerHTML = '<li class="history-empty">Henuz kayit yok.</li>';
      return;
    }
    list.innerHTML = items
      .map(
        (h) => `
      <li class="history-item ${h.is_favorite ? "is-fav" : ""}" data-id="${h.id}">
        <button type="button" class="history-fav" data-fav="${h.id}" title="Favori">${h.is_favorite ? "★" : "☆"}</button>
        <button type="button" class="history-fill" data-fill="${h.id}">
          <span class="history-topic">${escapeHtml(h.label || h.topic)}</span>
          <span class="history-meta">${escapeHtml(h.platform)} · ${escapeHtml(h.language)}${h.tts_engine ? ` · ${escapeHtml(h.tts_engine)}` : ""}</span>
        </button>
        <button type="button" class="history-delete danger btn-sm" data-del="${h.id}" title="Gecmisten sil">Sil</button>
      </li>`
      )
      .join("");

    const byId = Object.fromEntries(items.map((h) => [h.id, h]));

    list.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm("Bu gecmis kaydini silmek istiyor musun?")) return;
        const res = await fetch(`/api/history/${btn.dataset.del}`, { method: "DELETE" });
        if (!res.ok) {
          let data = {};
          try {
            data = await readApiJson(res);
          } catch (e) {
            data = { detail: e.message };
          }
          setStatus(data.detail || "Silinemedi", true);
          return;
        }
        loadHistory();
      });
    });

    list.querySelectorAll("[data-fav]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await fetch(`/api/history/${btn.dataset.fav}/favorite`, { method: "PATCH" });
        loadHistory();
      });
    });

    list.querySelectorAll("[data-fill]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const h = byId[btn.dataset.fill];
        if (!h) return;
        $("subject").value = h.topic;
        if ($("platform")) $("platform").value = h.platform || "tiktok";
        applyPlatformFromSelect();
        if ($("production-lang")) $("production-lang").value = h.language || "tr";
        if ($("tts-engine") && h.tts_engine) $("tts-engine").value = h.tts_engine;
        refreshAllCustomSelects();
      });
    });
  } catch (e) {
    const hint = e?.message ? `: ${escapeHtml(e.message)}` : "";
    list.innerHTML = `<li class="history-empty">Gecmis yuklenemedi${hint}</li>`;
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function pollTask(taskId) {
  const r = await fetch(`/api/tasks/${taskId}`);
  const data = await readApiJson(r);
  if (!r.ok) throw apiError(data, "Gorev sorgulanamadi");
  return data;
}

function getBatchTopics() {
  return [...document.querySelectorAll(".batch-topic-input")]
    .map((i) => i.value.trim())
    .filter(Boolean);
}

function batchIcon(state, progress) {
  if (state === 1) return "✅";
  if (state === -1) return "❌";
  if (state === 4) return "⏳";
  return "⏸";
}

function batchTaskStatus(t) {
  const prodLabel = (sec) => (sec > 0 ? ` · ${formatVcDuration(sec)}` : "");
  if (t.state === 4) {
    if (t.phase === "awaiting_ai_visuals") {
      const st = t.ai_prompts_status || "";
      if (st === "generating") return "AI gorsel — promptlar uretiliyor…";
      if (st === "minimax_running") {
        const mp = t.minimax_progress;
        const extra = mp?.total ? ` ${mp.done || 0}/${mp.total}` : "";
        return `H3 Studio uretiyor${extra}… ${t.minimax_status_text || ""}`.trim();
      }
      if (st === "error") return "AI gorsel — prompt hatasi (yine de dosya yukleyebilirsin)";
      if (t.minimax_status === "error") {
        return `H3 Studio hata — elle yukle: ${t.minimax_error || ""}`.slice(0, 120);
      }
      return "AI gorsel — Pinokio + dosya sec, Montaja devam";
    }
    const elapsed =
      t.phase === "en"
        ? t.en_production_elapsed_sec || t.production_elapsed_sec
        : t.production_elapsed_sec;
    const elapsedLbl = elapsed > 0 ? ` · ${formatVcDuration(elapsed)}` : "";
    const [l1, l2] = taskLangCodes(t);
    if (t.phase === "en") return `2/2 ${l2} (${t.step || "..."}) ${t.progress || 0}%${elapsedLbl}`;
    if (t.dual_language && t.phase === "tr") {
      return `1/2 ${l1} (${t.step || "..."}) ${t.progress || 0}%${elapsedLbl}`;
    }
    return `Uretiliyor (${t.step || "..."}) ${t.progress || 0}%${elapsedLbl}`;
  }
  if (t.state === 1) {
    const [l1, l2] = taskLangCodes(t);
    if (t.dual_language && t.production_sec && t.en_production_sec) {
      return `${l1} + ${l2} tamam · ${l1} ${formatVcDuration(t.production_sec)} · ${l2} ${formatVcDuration(t.en_production_sec)}`;
    }
    const sec =
      t.phase === "en" || t.en_production_sec
        ? t.en_production_sec || t.production_sec
        : t.production_sec;
    if (t.dual_language && !t.en_task_id) {
      return `${l1} tamam · ${l2} eksik${prodLabel(sec)}`;
    }
    const dualLbl = t.dual_language ? `${l1} + ${l2} tamam` : "Tamamlandi";
    return `${dualLbl}${prodLabel(sec)}`;
  }
  if (t.state === -1) {
    if (t.dual_language && t.tr_done && t.en_error) {
      const [l1, l2] = taskLangCodes(t);
      return `${l1} hazir · ${l2} hata: ${t.en_error}`;
    }
    return t.error || "Hata";
  }
  return "Bekliyor";
}

function queueStatusLabel(status) {
  const map = {
    pending: "Sirada",
    running: "Uretiliyor",
    done: "Tamam",
    failed: "Hata",
    cancelled: "Iptal",
  };
  return map[status] || status;
}

function queueKindLabel(kind) {
  if (kind === "batch") return "Seri";
  if (kind === "single") return "Kisa";
  if (kind === "longform") return "Uzun";
  return kind;
}

function buildBatchRequestBody(topics, { scripts = null, dualLang = null } = {}) {
  const dual = dualLang != null ? dualLang : !!$("dual-language")?.checked;
  const tts = $("tts-engine")?.value || "edge";
  const videoSource = $("source")?.value || "pexels";
  const pinokio = videoSource === "pinokio";
  return {
    topics,
    scripts: scripts?.length ? scripts : undefined,
    platform: $("platform")?.value || "tiktok",
    video_aspect: getAspect(),
    video_source: videoSource,
    production_mode: $("production-mode-manual")?.checked ? "manual" : "automatic",
    production_language: $("production-lang")?.value || "tr",
    dual_language: dual,
    second_language: dual ? dualSecondLang() : null,
    tts_engine: tts,
    tts_provider: tts,
    niche: $("niche")?.value || "genel",
    niche_experimental: !!$("niche-experimental")?.checked,
    edge_voice: formEdgeVoice(),
    dual_llm: !!($("dual-llm")?.checked),
    editor_web_verify: !!($("editor-web-verify")?.checked),
    strengthen_hook: !!($("strengthen-hook")?.checked),
    writer_model: currentWriterModel() || null,
    editor_model: currentEditorModel() || null,
    rvc_voice: formRvcVoice(),
    rvc_pitch: Number($("rvc-pitch")?.value || 0),
    rvc_index_rate: Number($("rvc-index-rate")?.value || 1),
    voice_rate: formVoiceRate(),
    bgm_mode: $("bgm-mode")?.value || "niche",
    bgm_track: $("bgm-track")?.value || null,
    bgm_volume: Number($("bgm-volume")?.value || 20) / 100,
    outro_id: ($("outro")?.value || "").trim() || null,
    video_clip_duration: getClipDuration(),
    subtitle_style: buildSubtitleStylePayload(),
    auto_retry_failed: true,
    auto_retry_rounds: 2,
    use_lang_preset: false,
    ai_manual_visuals: pinokio,
    ai_visual_continue: pinokio || !!$("ai-visual-continue")?.checked,
    ai_visual_segments: (() => {
      const v = Number($("ai-visual-segments")?.value);
      return Number.isFinite(v) && v >= 9 ? Math.min(12, Math.round(v)) : null;
    })(),
    ai_visual_auto_minimax: pinokio || !!$("ai-visual-auto-minimax")?.checked,
  };
}

async function enqueueBatchProduction(topics, { scripts = null, dualLang = null, silent = false } = {}) {
  saveLastVoiceFromForm();
  const body = buildBatchRequestBody(topics, { scripts, dualLang });
  const res = await fetch("/api/batch/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: generateAbortController?.signal,
  });
  const data = await readApiJson(res);
  if (!res.ok) throw apiError(data, "Uretim kuyruga eklenemedi");
  if (data.batch_id) {
    currentBatchId = data.batch_id;
    focusOutputJob(data.batch_id, "batch");
  }
  $("batch-progress-wrap")?.classList.remove("hidden");
  if (!silent) {
    if (data.already_running) {
      const msg = data.message || "Bu konu zaten uretiliyor — yeni sira eklenmedi.";
      pushQueueNotification(msg);
      showToast(msg, 4500);
      setStatus(msg);
    } else {
      const pos = data.position || 1;
      const msg = pos > 1 ? `Siraya alindi (${pos}. sira)` : "Uretim kuyrugunda — basliyor...";
      pushQueueNotification(msg);
      if (pos > 1) showToast(msg, 4000);
      else setStatus("Uretim kuyrugunda — basliyor...");
    }
  }
  startQueuePolling();
  return data;
}

async function removeQueueItem(queueId) {
  const id = String(queueId || "").trim();
  if (!id) return;
  try {
    const res = await fetch(`/api/queue/${encodeURIComponent(id)}`, { method: "DELETE" });
    const data = await readApiJson(res);
    if (!res.ok) throw apiError(data, "Kuyruk satiri silinemedi");
    showToast("Kuyruktan cikarildi", 2500);
    startQueuePolling();
  } catch (err) {
    showToast(err?.message || "Kuyruk satiri silinemedi", 4000);
  }
}

function queuePartRow(icon, label, status) {
  return `<li class="production-queue-part">
    <span class="production-queue-part-icon">${icon}</span>
    <span class="production-queue-part-label">${escapeHtml(label)}</span>
    <span class="production-queue-part-status">${escapeHtml(status)}</span>
  </li>`;
}

/** Aktif isin alt parcalarini gosterir: seri = her video, uzun = her bolum. */
function queueItemParts(it) {
  const prog = it.progress;
  if (!prog || (it.status !== "running" && it.status !== "pending")) return "";
  let rows = "";
  if (it.kind === "longform") {
    const chapters = prog.chapters || [];
    if (!chapters.length) return "";
    rows = chapters
      .map((ch, i) => {
        const label = ch.display_title || chapterDisplayTitle(prog.main_subject, ch.title) || `Bolum ${i + 1}`;
        const st = ch.state ?? (prog.state === 1 ? 1 : 0);
        let status = "Bekliyor";
        if (st === 1) status = "Senaryo hazir";
        else if (st === 4) status = `${prog.step || "Uretiliyor"} ${prog.progress || 0}%`;
        else if (st === -1) status = "Hata";
        return queuePartRow(batchIcon(st, prog.progress), `${i + 1}. ${label}`, status);
      })
      .join("");
    if (prog.script_done || prog.state === 1 || (prog.task_id && prog.state === 4)) {
      const dual = !!prog.dual_language;
      const assetIcon = prog.state === 1 ? "✅" : "⏳";
      const assetStatus =
        prog.state === 1
          ? "Ses + altyazi + gorseller hazir"
          : `${prog.phase === "en" ? "EN" : "TR"} ses/altyazi/gorsel · ${prog.step || "..."} ${prog.progress || 0}%`;
      rows += queuePartRow(assetIcon, dual ? "Montaj paketi (TR + EN)" : "Montaj paketi", assetStatus);
    }
  } else {
    const tasks = prog.tasks || [];
    if (!tasks.length) return "";
    rows = tasks
      .map((t, i) => queuePartRow(batchIcon(t.state, t.progress), `${i + 1}. ${t.topic || "Video"}`, batchTaskStatus(t)))
      .join("");
  }
  return `<ul class="production-queue-parts">${rows}</ul>`;
}

function renderProductionQueue(q) {
  const lists = productionQueueListEls();
  const items = q?.items || [];
  syncQueueActiveFromSnapshot(q);
  queueWorkerAlive = q?.worker_alive !== false;
  // Sira yalnizca aktif isler — bitenler cikti/galeride kalir.
  const active = items.filter((it) => it.status === "pending" || it.status === "running");
  const html = active.length
    ? active
        .map((it) => {
          const isCurrent = it.status === "running";
          const prog = it.progress;
          let detail = "";
          if (it.status === "running" && prog) {
            if (it.kind === "longform") {
              detail = ` — ${prog.done || 0}/${prog.total || 0} bolum`;
            } else if (prog.total) {
              detail = ` — ${prog.done || 0}/${prog.total} video`;
            }
          }
          const canDrop = it.status === "pending";
          const dropBtn = canDrop
            ? `<button type="button" class="production-queue-drop" data-queue-id="${escapeHtml(it.queue_id)}" title="Siradan cikar" aria-label="Siradan cikar">×</button>`
            : "";
          return `<li class="production-queue-item${isCurrent ? " is-current" : ""} status-${it.status}">
        <div class="production-queue-head">
          <span class="production-queue-pos">${it.position}</span>
          <span class="production-queue-kind">${escapeHtml(queueKindLabel(it.kind))}</span>
          <span class="production-queue-label">${escapeHtml(it.label)}</span>
          <span class="production-queue-status">${escapeHtml(queueStatusLabel(it.status))}${detail}</span>
          ${dropBtn}
        </div>
        ${queueItemParts(it)}
      </li>`;
        })
        .join("")
    : "";
  for (const list of lists) {
    list.innerHTML = html;
    list.querySelectorAll(".production-queue-drop").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        removeQueueItem(btn.getAttribute("data-queue-id"));
      });
    });
  }
  if (!active.length) clearQueuePanelProgress();
  updateProductionStopUi();
}

function clearQueuePanelProgress() {
  const batchWrap = $("batch-progress-wrap");
  if (batchWrap) {
    batchWrap.classList.add("hidden");
    const lines = $("batch-task-lines");
    if (lines) lines.innerHTML = "";
    const fill = $("batch-progress-fill");
    if (fill) fill.style.width = "0%";
    const text = $("batch-progress-text");
    if (text) text.textContent = "0/0";
  }
  const longWrap = $("longform-progress-wrap");
  if (longWrap) {
    longWrap.classList.add("hidden");
    const lines = $("longform-task-lines") || $("longform-chapter-lines");
    if (lines) lines.innerHTML = "";
  }
}

function startQueuePolling() {
  if (queuePollTimer) return;
  queuePollTimer = setInterval(() => pollProductionQueue().catch(() => {}), 2500);
  pollProductionQueue().catch(() => {});
}

async function processBatchArchives(data, aspect = getAspect()) {
  const preview = isOutputFocusedRef(data.batch_id);
  const dualBatch = !!data.dual_language;
  for (const t of data.tasks || []) {
    const isDual = dualBatch || !!t.dual_language;
    const [l1, l2] = taskLangCodes(t);
    const trKey = `tr:${t.task_id}`;
    if (isDual && t.tr_done && t.task_id && !archivedBatchTasks.has(trKey)) {
      const trScript = (t.script || "").trim();
      const archived = await archiveToGallery(
        t.task_id,
        t.topic,
        t.videos || [],
        aspect,
        trScript,
        null,
        {
          language: l1.toLowerCase(),
          notify: false,
          platform: $("platform")?.value || "",
          niche: $("niche")?.value || "",
          production_sec: t.production_sec || 0,
        }
      );
      if (archived) {
        archivedBatchTasks.add(trKey);
        showArchivedInOutput(archived, preview);
      }
    }
    const enKey = `en:${t.en_task_id}`;
    if (t.state === 1 && t.en_task_id && !archivedBatchTasks.has(enKey)) {
      const enTopic = `${t.topic} (${l2})`;
      const enScript = (t.en_script || "").trim();
      const archived = await archiveToGallery(
        t.en_task_id,
        enTopic,
        t.en_videos || [],
        aspect,
        enScript,
        null,
        {
          language: l2.toLowerCase(),
          notify: false,
          notify_subject: t.topic,
          notifyBody: `Video hazir (${l1}+${l2}): ${(t.topic || "Video").slice(0, 72)}`,
          platform: $("platform")?.value || "",
          niche: $("niche")?.value || "",
          production_sec: t.en_production_sec || 0,
        }
      );
      if (archived) {
        archivedBatchTasks.add(enKey);
        showArchivedInOutput(archived, preview);
      }
    }
    if (t.state === 1 && !isDual && t.task_id && !archivedBatchTasks.has(`single:${t.task_id}`)) {
      const singleKey = `single:${t.task_id}`;
      const prodLang = $("production-lang")?.value || "tr";
      const scriptText = (t.script || "").trim();
      const archived = await archiveToGallery(
        t.task_id,
        t.topic,
        t.videos || [],
        aspect,
        scriptText,
        null,
        {
          language: prodLang,
          notify: false,
          platform: $("platform")?.value || "",
          niche: $("niche")?.value || "",
          production_sec: t.production_sec || 0,
        }
      );
      if (archived) {
        archivedBatchTasks.add(singleKey);
        showArchivedInOutput(archived, preview);
      }
    }
  }
  if ((data.tasks || []).some((task) => task.state === 1)) {
    void loadHistory();
  }
  void backfillGalleryPublishPacks();
}

async function processLongformArchives(data) {
  if (data?.mode === "assets") return;
  const aspect = getLongformAspect();
  const niche = $("longform-niche")?.value || "genel";
  const platform = $("longform-platform")?.value || "youtube";
  const main = (data.main_subject || $("longform-subject")?.value || "").trim();
  const quick = { generate_caption: false };
  for (const ch of data.chapters || []) {
    const sub = (ch.title || "").trim();
    const topic = main && sub ? `${main} — ${sub}` : ch.topic || longformChapterTopic(ch.index, ch.title);
    if (data.dual_language) {
      const trKey = `lf-tr:${ch.task_id}`;
      if (ch.tr_done && ch.task_id && !archivedLongformTasks.has(trKey)) {
        const trScript = (ch.script || "").trim();
        const archived = await archiveToGallery(
          ch.task_id,
          topic,
          ch.videos || [],
          aspect,
          trScript,
          null,
          { language: "tr", niche, platform, notify: false, ...quick }
        );
        if (archived) archivedLongformTasks.add(trKey);
      }
      const enKey = `lf-en:${ch.en_task_id}`;
      if (ch.state === 1 && ch.en_task_id && !archivedLongformTasks.has(enKey)) {
        const enTopic = `${topic} (EN)`;
        const enScript = (ch.en_script || "").trim();
        const archived = await archiveToGallery(
          ch.en_task_id,
          enTopic,
          ch.en_videos || [],
          aspect,
          enScript,
          null,
          {
            language: "en",
            niche,
            platform,
            notify_subject: topic,
            notifyBody: `Video hazir (TR+EN): ${(topic || "Video").slice(0, 72)}`,
            ...quick,
          }
        );
        if (archived) archivedLongformTasks.add(enKey);
      }
    } else {
      const singleKey = `lf-single:${ch.task_id}`;
      if (ch.state === 1 && ch.task_id && !archivedLongformTasks.has(singleKey)) {
        const prodLang = $("production-lang")?.value || "tr";
        const scriptText = (ch.script || "").trim();
        const archived = await archiveToGallery(
          ch.task_id,
          topic,
          ch.videos || [],
          aspect,
          scriptText,
          null,
          { language: prodLang, niche, platform, ...quick }
        );
        if (archived) archivedLongformTasks.add(singleKey);
      }
    }
  }
  if ((data.chapters || []).some((ch) => ch.state === 1)) {
    void loadHistory();
  }
}

function onQueueDrain(q) {
  releaseLlmResources();
  $("btn-generate").disabled = !engineReady || !isLlmReady();
  updateLongformGenerateButton();
  clearQueuePanelProgress();
  for (const list of productionQueueListEls()) {
    list.innerHTML = "";
  }
  if (!queueCompletionNotified) {
    queueCompletionNotified = true;
    pushQueueNotification("Uretim kuyrugu tamamlandi");
    void notifyDone("AkiFactory", "Uretim kuyrugu tamamlandi", QUEUE_NOTIFY_KEY);
  }
  void loadGallery();
  void loadGalleryStats();
  void loadHistory();
  void loadProducedTopics();
  void loadTopicMemoryHint();
  void prefetchGalleryPublishBackfill();
  syncQueueActiveFromSnapshot(q || { processing: false, active_count: 0 });
  updateProductionStopUi();
  if (productionMode) endProduction();
  void showLatestOutput({ autoplay: false });
}

function batchArchivesPending(data) {
  const dualBatch = !!data.dual_language;
  for (const t of data.tasks || []) {
    const isDual = dualBatch || !!t.dual_language;
    if (isDual && t.tr_done && t.task_id && !archivedBatchTasks.has(`tr:${t.task_id}`)) return true;
    if (t.state === 1 && t.en_task_id && !archivedBatchTasks.has(`en:${t.en_task_id}`)) return true;
    if (t.state === 1 && !isDual && t.task_id && !archivedBatchTasks.has(`single:${t.task_id}`)) {
      return true;
    }
  }
  return false;
}

function longformArchivesPending(data) {
  if (data?.mode === "assets") return false;
  for (const ch of data.chapters || []) {
    const topic = ch.topic || longformChapterTopic(ch.index, ch.title);
    void topic;
    if (data.dual_language) {
      if (ch.tr_done && ch.task_id && !archivedLongformTasks.has(`lf-tr:${ch.task_id}`)) return true;
      if (ch.state === 1 && ch.en_task_id && !archivedLongformTasks.has(`lf-en:${ch.en_task_id}`)) {
        return true;
      }
    } else if (ch.state === 1 && ch.task_id && !archivedLongformTasks.has(`lf-single:${ch.task_id}`)) {
      return true;
    }
  }
  return false;
}

async function ensureJobFinalized(kind, refId) {
  if (!refId) return;
  const key = `${kind}:${refId}`;
  if (finalizedQueueJobs.has(key)) return;
  try {
    if (kind === "longform") {
      const r = await fetch(`/api/longform/${refId}`);
      if (!r.ok) return;
      const data = await readApiJson(r);
      const focusOutput = isOutputFocusedRef(refId);
      // Kuyruk panelini eski isle doldurma — sadece arsiv + odakli cikti.
      if (focusOutput) {
        showLongformProgress(data, { outputPipeline: true, queuePanel: false });
      }
      await processLongformArchives(data);
      updateLongformRetryUi(data);
      if (!longformArchivesPending(data)) finalizedQueueJobs.add(key);
    } else {
      const r = await fetch(`/api/batch/${refId}`);
      if (!r.ok) return;
      const data = await readApiJson(r);
      const focusOutput = isOutputFocusedRef(refId);
      if (focusOutput) {
        showBatchProgress(data, { outputPipeline: true, queuePanel: false });
      }
      await processBatchArchives(data);
      if (!batchArchivesPending(data)) finalizedQueueJobs.add(key);
    }
  } catch {
    /* sonraki poll'da tekrar dene */
  }
}

async function finalizeCompletedQueueItems(q) {
  for (const it of q.items || []) {
    if (it.status !== "done" || !it.ref_id) continue;
    const kind = it.kind === "longform" ? "longform" : "batch";
    await ensureJobFinalized(kind, it.ref_id);
  }
}

async function pollProductionQueue() {
  const r = await fetch("/api/queue");
  if (!r.ok) return;
  const q = await readApiJson(r);
  const prevCurrent = queuePollLastCurrent;
  const curId = q.current?.ref_id;
  if (prevCurrent?.ref_id && prevCurrent.ref_id !== curId) {
    const kind = prevCurrent.kind === "longform" ? "longform" : "batch";
    void ensureJobFinalized(kind, prevCurrent.ref_id);
  }
  if (curId) {
    queuePollLastCurrent = { ref_id: curId, kind: q.current.kind };
  } else if (!(q.active_count || 0) && !q.processing) {
    queuePollLastCurrent = null;
  }
  renderProductionQueue(q);
  updatePill();
  const stillActive =
    (q.active_count || 0) > 0 || !!q.processing || (q.pending_count || 0) > 0;
  if (stillActive && !q.worker_alive && (q.pending_count || 0) > 0) {
    pushQueueNotification("Kuyruk isci yeniden baslatiliyor…", "warn");
    showToast("Kuyruk isci yeniden baslatiliyor…", 2500);
  }
  const current = q.current;
  if (current?.progress) {
    const driveOutput = shouldDriveOutputPipeline(current);
    if (current.kind === "longform") {
      currentLongformId = current.ref_id;
      showLongformProgress(current.progress, {
        outputPipeline: driveOutput,
        queuePanel: true,
      });
      void processLongformArchives(current.progress);
      updateLongformRetryUi(current.progress);
    } else {
      currentBatchId = current.ref_id;
      showBatchProgress(current.progress, {
        outputPipeline: driveOutput,
        queuePanel: true,
      });
      void processBatchArchives(current.progress);
    }
    if (!driveOutput) updateOutputQueueWaitHint(q);
  } else if (!stillActive) {
    clearQueuePanelProgress();
  }
  void finalizeCompletedQueueItems(q);
  if (!stillActive) {
    if (currentBatchId) await ensureJobFinalized("batch", currentBatchId);
    if (currentLongformId) await ensureJobFinalized("longform", currentLongformId);
    if (queuePollTimer) {
      clearInterval(queuePollTimer);
      queuePollTimer = null;
    }
    onQueueDrain(q);
  }
}

function showBatchProgress(data, { outputPipeline = true, queuePanel = true } = {}) {
  const wrap = $("batch-progress-wrap");
  if (queuePanel && wrap) {
    wrap.classList.remove("hidden");
    const total = data.total || 0;
    const done = data.done || 0;
    const pct = total ? Math.round((done / total) * 100) : 0;
    const fill = $("batch-progress-fill");
    if (fill) fill.style.width = `${pct}%`;
    const text = $("batch-progress-text");
    const dualLbl = data.dual_language ? " (cift dil)" : "";
    if (text) text.textContent = `${done}/${total} konu tamamlandi${dualLbl}`;
    const lines = $("batch-task-lines");
    if (lines) {
      lines.innerHTML = (data.tasks || [])
        .map((t) => {
          return `<li><span><span class="batch-icon">${batchIcon(t.state, t.progress)}</span>${escapeHtml(t.topic)}</span><span>${escapeHtml(batchTaskStatus(t))}</span></li>`;
        })
        .join("");
    }
  }
  syncBatchTopicRows(data);
  syncAiVisualAwaiting(data);
  if (!outputPipeline) return;
  const total = data.total || 0;
  const done = data.done || 0;
  const running = (data.tasks || []).find((t) => t.state === 4);
  if (running) {
    if (!pipelineRuntime.short || pipelineRuntime.short.presetKey !== "videoEngine") {
      startPipeline(
        "short",
        "videoEngine",
        data.dual_language ? "Seri uretim (cift dil)" : "Seri uretim",
        `${done}/${total} konu tamam`
      );
    }
    if (running.phase === "awaiting_ai_visuals") {
      updatePipelineFromEngine(
        "short",
        35,
        "AI gorsel",
        running.topic || "Promptlar + dosya"
      );
    } else {
      const [l1, l2] = taskLangCodes(running);
      const prefix = running.dual_language
        ? running.phase === "en"
          ? running.tr_done
            ? `2/2 ${l2} · ${running.topic} — ${l1} galeride`
            : `2/2 ${l2} · ${running.topic}`
          : `1/2 ${l1} · ${running.topic}`
        : running.topic;
      updatePipelineFromEngine("short", running.progress, running.step, prefix);
    }
  } else if ((data.tasks || []).every((t) => t.state === 1 || t.state === -1) && !data.cancelled) {
    clearBatchTopicListIfDone(data);
    if (data.failed) {
      failPipeline("short", `Seri bitti — ${data.failed} hata`);
    } else {
      completePipeline("short", "Seri uretim tamamlandi");
    }
  }
}

function setLongformStatus(msg, isError = false) {
  const el = $("longform-status");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("err", !!isError);
}

function turkishGenitive(phrase) {
  const p = (phrase || "").trim().replace(/\.$/, "");
  if (!p) return p;
  if (/['\u2019]/.test(p)) return p;
  let lastV = "a";
  for (let i = p.length - 1; i >= 0; i -= 1) {
    const c = p[i].toLowerCase();
    if ("aeiouöüı".includes(c)) {
      lastV = c;
      break;
    }
  }
  const map = { a: "ın", ı: "ın", o: "un", u: "un", e: "in", i: "in", ö: "ün", ü: "ün" };
  const suf = map[lastV] || "ın";
  const endsVowel = /[aeiouöüı]$/i.test(p);
  return endsVowel ? `${p}n${suf}` : `${p}${suf}`;
}

function chapterDisplayTitle(main, title) {
  const m = (main || "").trim();
  const t = (title || "").trim();
  if (!t) return "";
  if (!m) return t;
  if (t.toLowerCase().startsWith(m.toLowerCase())) return t;
  return `${turkishGenitive(m)} ${t}`;
}

function normalizeLongformChapter(ch) {
  if (ch && typeof ch === "object") {
    return {
      title: String(ch.title || "").trim(),
      script: String(ch.script || "").trim(),
    };
  }
  return { title: String(ch || "").trim(), script: "" };
}

function longformJobAssetsLinks(data) {
  const ga = data.gallery_assets || {};
  const assets =
    ga.script_url || ga.chapters?.length || ga.audio_url ? ga : data.assets || {};
  const assetsEn = data.gallery_assets?.audio_en_url
    ? {
        audio_url: data.gallery_assets.audio_en_url,
        subtitle_url: data.gallery_assets.subtitle_en_url,
        script_url: data.gallery_assets.script_en_url,
      }
    : data.assets_en || {};
  const dual = !!data.dual_language;
  const bits = [];
  const ready = data.state === 1;
  if (ready && assets.script_url) {
    bits.push(
      `<a class="longform-asset-link" href="${escapeHtml(assets.script_url)}" download>TR senaryo (tam)</a>`
    );
  }
  const chapterAssets = assets.chapters || [];
  if (ready && chapterAssets.length) {
    bits.push(
      `<span class="longform-asset-link longform-asset-clips-label">${chapterAssets.length} bolum paketi</span>`
    );
  }
  if (ready && assets.audio_url && !chapterAssets.length) {
    bits.push(
      `<a class="longform-asset-link" href="${escapeHtml(assets.audio_url)}" download>TR ses</a>`
    );
  }
  if (ready && assets.subtitle_url && !chapterAssets.length) {
    bits.push(
      `<a class="longform-asset-link" href="${escapeHtml(assets.subtitle_url)}" download>TR altyazi</a>`
    );
  }
  if (ready && assets.script_url && !chapterAssets.length) {
    bits.push(
      `<a class="longform-asset-link" href="${escapeHtml(assets.script_url)}" download>TR senaryo</a>`
    );
  }
  if (ready && chapterAssets.length) {
    chapterAssets.forEach((ch) => {
      const label = escapeHtml(
        ch.display_title || ch.title || ch.slug || `Bolum ${Number(ch.index) + 1}`
      );
      if (ch.audio_tr_url) {
        bits.push(
          `<a class="longform-asset-link" href="${escapeHtml(ch.audio_tr_url)}" download title="${label}">${label} ses</a>`
        );
      }
      if (ch.subtitle_tr_url) {
        bits.push(
          `<a class="longform-asset-link" href="${escapeHtml(ch.subtitle_tr_url)}" download title="${label}">${label} altyazi</a>`
        );
      }
    });
  }
  if (ready && assets.clips?.length) {
    bits.push(
      `<span class="longform-asset-link longform-asset-clips-label">${assets.clips.length} klip/gorsel</span>`
    );
    assets.clips.slice(0, 4).forEach((c) => {
      bits.push(
        `<a class="longform-asset-link" href="${escapeHtml(c.url)}" download title="${escapeHtml(c.name)}">${c.kind === "image" ? "Gorsel" : "Klip"}</a>`
      );
    });
    if (assets.clips.length > 4) {
      bits.push(`<span class="hint">+${assets.clips.length - 4}</span>`);
    }
  }
  if (data.gallery_entry_id && ready) {
    bits.push(
      `<button type="button" class="btn-ghost btn-sm longform-open-gallery-folder" data-lf-gallery="${escapeHtml(data.gallery_entry_id)}">Galeri klasoru</button>`
    );
  }
  if (dual && ready && assetsEn.audio_url) {
    bits.push(
      `<a class="longform-asset-link" href="${escapeHtml(assetsEn.audio_url)}" download>EN ses</a>`
    );
  }
  if (dual && ready && assetsEn.subtitle_url) {
    bits.push(
      `<a class="longform-asset-link" href="${escapeHtml(assetsEn.subtitle_url)}" download>EN altyazi</a>`
    );
  }
  return bits.length ? `<div class="longform-job-assets">${bits.join(" · ")}</div>` : "";
}

function longformChapterAssetsLinks(ch, dual) {
  void ch;
  void dual;
  return "";
}

function updateLongformGenerateButton() {
  const btn = $("btn-longform-generate");
  if (!btn) return;
  btn.disabled =
    longformChapters.length === 0 || !engineReady || !isLlmReady();
}

function updateLongformPlanSummary() {
  const el = $("longform-plan-summary");
  const subject = $("longform-subject")?.value?.trim() || "";
  if (!el) return;
  if (!longformChapters.length) {
    el.className = "longform-plan-summary empty";
    el.innerHTML = "<p>Once ana konu yazin ve <strong>Bolumleri planla</strong> deyin.</p>";
    return;
  }
  const dual = !!$("longform-dual-language")?.checked;
  el.className = "longform-plan-summary";
  el.innerHTML = `
    <p><strong>${escapeHtml(subject || "Ana konu")}</strong></p>
    <p class="hint">${longformChapters.length} alt baslik — bolum bolum ses + altyazi${dual ? " (TR + EN)" : ""}</p>
    <ol class="longform-summary-list">${longformChapters
      .map((ch) => {
        const row = normalizeLongformChapter(ch);
        return `<li>${escapeHtml(chapterDisplayTitle(subject, row.title))}</li>`;
      })
      .join("")}</ol>
  `;
}

function renderLongformChapters() {
  const list = $("longform-chapter-list");
  const countEl = $("longform-chapter-count");
  if (!list) return;
  const n = longformChapters.length;
  if (countEl) countEl.textContent = `${n} bolum`;
  updateLongformGenerateButton();
  if (!n) {
    list.innerHTML = "";
    updateLongformPlanSummary();
    return;
  }
  list.innerHTML = longformChapters
    .map((ch, i) => {
      const row = normalizeLongformChapter(ch);
      const display = chapterDisplayTitle($("longform-subject")?.value?.trim() || "", row.title);
      return `
    <li class="longform-chapter-row">
      <span class="longform-chapter-num">${i + 1}</span>
      <div class="longform-chapter-body">
        <input type="text" class="longform-chapter-input" data-idx="${i}" data-field="title" value="${escapeHtml(row.title)}" placeholder="Orn: tarihcesi, kesfi, icerigi" />
        <span class="hint longform-chapter-expanded">${escapeHtml(display)}</span>
        <details class="longform-chapter-script-wrap">
          <summary>Senaryo (istege bagli — manuel)</summary>
          <textarea class="longform-chapter-script" data-idx="${i}" rows="4" placeholder="Bos birak: LLM uretir. Doldur: bu metinle ses + altyazi olusur.">${escapeHtml(row.script)}</textarea>
        </details>
      </div>
      <button type="button" class="batch-remove longform-chapter-remove" data-idx="${i}" title="Kaldir">&times;</button>
    </li>`;
    })
    .join("");
  list.querySelectorAll(".longform-chapter-input, .longform-chapter-script").forEach((el) => {
    el.addEventListener("input", () => {
      const idx = Number(el.dataset.idx);
      const field = el.dataset.field || (el.classList.contains("longform-chapter-script") ? "script" : "title");
      if (!Number.isFinite(idx) || idx < 0 || idx >= longformChapters.length) return;
      const cur = normalizeLongformChapter(longformChapters[idx]);
      if (field === "script") cur.script = el.value;
      else cur.title = el.value;
      longformChapters[idx] = cur;
      if (field === "title") {
        updateLongformPlanSummary();
        const expanded = list.querySelector(
          `.longform-chapter-row:nth-child(${idx + 1}) .longform-chapter-expanded`
        );
        if (expanded) {
          expanded.textContent = chapterDisplayTitle(
            $("longform-subject")?.value?.trim() || "",
            cur.title
          );
        }
      }
    });
  });
  list.querySelectorAll(".longform-chapter-remove").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.dataset.idx);
      if (Number.isFinite(idx)) {
        longformChapters.splice(idx, 1);
        renderLongformChapters();
      }
    });
  });
  updateLongformPlanSummary();
}

function getLongformAspect() {
  const sel = $("longform-aspect")?.value;
  if (sel === "16:9" || sel === "9:16" || sel === "1:1") return sel;
  const id = $("longform-platform")?.value || "youtube";
  if (id === "custom") return $("aspect")?.value || "16:9";
  const p = platformProfile(id);
  return p?.aspect_ratio || "16:9";
}

function getLongformClipDuration() {
  const aspect = getLongformAspect();
  if (aspect === "16:9") return 10;
  if (aspect === "1:1") return 8;
  const id = $("longform-platform")?.value || "youtube_shorts";
  const p = platformProfile(id);
  return Number(p?.max_clip_duration) || 7;
}

function syncLongformAspectFromPlatform() {
  const sel = $("longform-aspect");
  if (!sel) return;
  const id = $("longform-platform")?.value || "youtube";
  const p = platformProfile(id);
  const ratio = p?.aspect_ratio;
  if (ratio === "16:9" || ratio === "9:16" || ratio === "1:1") {
    sel.value = ratio;
  }
  updateLongformAspectHint();
}

function updateLongformAspectHint() {
  const el = $("longform-aspect-hint");
  if (!el) return;
  const a = getLongformAspect();
  if (a === "16:9") {
    el.textContent =
      "Yatay stok klipler + ~10 sn kesim. Qwen/H3 Studio promptlari 16:9 yazar.";
  } else if (a === "1:1") {
    el.textContent = "Kare kadraj stok/AI; klip suresi ~8 sn.";
  } else {
    el.textContent =
      "Dikey stok klipler + kisa kesim. Shorts/Reels montaji icin uygun.";
  }
}

function buildLongformSubtitleStylePayload() {
  const base = buildSubtitleStylePayload();
  const aspect = getLongformAspect();
  // Yatayda TikTok 72px cok buyuk — YouTube stilina kay
  if (aspect === "16:9" && (base.style_id || "") === "tiktok_classic") {
    return {
      ...base,
      style_id: "youtube",
      subtitle_position: base.subtitle_position || "bottom",
    };
  }
  if (aspect === "16:9" && !base.subtitle_position) {
    return { ...base, subtitle_position: "bottom" };
  }
  return base;
}

function longformChapterTopic(index, title) {
  const main = $("longform-subject")?.value?.trim() || "Video";
  const total = longformChapters.length;
  return `${main} — Bolum ${index + 1}/${total}: ${title}`;
}

function updateLongformRetryUi(data) {
  const row = $("longform-retry-row");
  const btn = $("btn-longform-retry");
  if (!row || !btn) return;
  const failed = data?.failed || 0;
  const running = data?.state === 4 || !!data?.running;
  const show = failed > 0 && !running && !!currentLongformId;
  row.classList.toggle("hidden", !show);
  btn.disabled = running || !engineReady || !isLlmReady();
}

function clearLongformArchiveKeysForRetry(chapters) {
  for (const ch of chapters || []) {
    if (ch.task_id) archivedLongformTasks.delete(`lf-tr:${ch.task_id}`);
    if (ch.en_task_id) archivedLongformTasks.delete(`lf-en:${ch.en_task_id}`);
    if (ch.task_id) archivedLongformTasks.delete(`lf-single:${ch.task_id}`);
  }
}

function showLongformProgress(data, { outputPipeline = true, queuePanel = true } = {}) {
  const wrap = $("longform-progress-wrap");
  const fill = $("longform-progress-fill");
  const text = $("longform-progress-text");
  const lines = $("longform-task-lines");
  if (queuePanel && wrap && lines) {
    wrap.classList.remove("hidden");
    const pct = data.state === 1 ? 100 : Math.max(0, Math.min(100, Number(data.progress) || 0));
    if (fill) fill.style.width = `${pct}%`;
    if (text) {
      const phaseLabel =
        data.phase === "en" ? "EN" : data.state === 4 ? "Uretiliyor" : data.state === 1 ? "Tamam" : "Bekliyor";
      text.textContent = `${pct}% — ${phaseLabel}${data.step ? ` · ${data.step}` : ""}`;
    }

    const chapters = data.chapters || [];
    const planLines = chapters
      .map((ch) => {
        const label = ch.display_title || chapterDisplayTitle(data.main_subject, ch.title);
        return `<li class="longform-plan-line hint"><span>${escapeHtml(String(ch.index + 1))}.</span> ${escapeHtml(label)}</li>`;
      })
      .join("");

    const assetsHtml = longformJobAssetsLinks(data);
    lines.innerHTML = `
    <li class="longform-task-line longform-task-main">
      <span><span class="batch-icon">${batchIcon(data.state, data.progress)}</span>${escapeHtml(data.main_subject || "Uzun video")}</span>
      <span>${escapeHtml(data.step || batchTaskStatus({ state: data.state, progress: data.progress }))}</span>
    </li>
    ${planLines ? `<ul class="longform-plan-lines">${planLines}</ul>` : ""}
    ${assetsHtml}
  `;
    lines.querySelectorAll(".longform-open-gallery-folder").forEach((btn) => {
      btn.addEventListener("click", () => {
        void openLongformGalleryFolder(btn.dataset.lfGallery).catch((e) => showToast(e.message, 5000));
      });
    });
  }

  if (!outputPipeline) {
    updateLongformRetryUi(data);
    return;
  }

  if (data.state === 4) {
    if (!pipelineRuntime.long || pipelineRuntime.long.presetKey !== "longformProduce") {
      startPipeline("long", "longformProduce", "Montajsiz paket", data.step || "Uretiliyor");
    }
    const blockIdx = data.phase === "en" ? 1 : 0;
    setPipelineStep(
      "long",
      blockIdx,
      `${data.step || "..."} ${data.progress || 0}%`
    );
  } else if (data.state === 1 && !data.cancelled) {
    completePipeline("long", "Ses, altyazi ve gorseller hazir");
    if (data.export_dir) {
      setLongformStatus(`Galeriye kaydedildi — Galeri > Uzun videolar sekmesinden klasoru acin.`);
    }
  } else if (data.state === -1 && !data.cancelled) {
    failPipeline("long", data.error || "Uretim hatasi");
  }
  updateLongformRetryUi(data);
}

async function pollLongform(longformId) {
  const r = await fetch(`/api/longform/${longformId}`);
  if (!r.ok) throw new Error("Uzun video sorgulanamadi");
  const data = await readApiJson(r);
  showLongformProgress(data);
  await processLongformArchives(data);
  const finished = data.state === 1 || data.state === -1;
  if (finished || data.cancelled) {
    clearInterval(longformPollTimer);
    longformPollTimer = null;
    updateLongformGenerateButton();
    if (data.cancelled || isProductionCancelled()) {
      if (!isProductionCancelled()) {
        failPipeline("long", "Uzun video uretimi iptal edildi");
        setLongformStatus("Uzun video uretimi iptal edildi.");
      }
    } else {
      const failed = data.failed || 0;
      setLongformStatus(
        failed
          ? `Hata: ${data.errors?.[0] || "Uretim basarisiz"}`
          : "Paket hazir — Galeri > Uzun videolar'dan klasoru acip montaja alin."
      );
      if (failed && data.errors?.length) {
        showToast(data.errors[0], 6000);
      }
      if (!queuePollTimer && !queueCompletionNotified) {
        queueCompletionNotified = true;
        notifyDone(
          "AkiFactory",
          data.dual_language ? "Uzun video paketi (TR+EN) hazir" : "Uzun video paketi hazir",
          `longform-done:${currentLongformId || ""}`
        );
      }
      void loadLongformGallery();
    }
    releaseLlmResources();
    updateLongformRetryUi(data);
    if (productionMode === "longform") {
      if (!data.failed) {
        currentLongformId = null;
      }
      endProduction();
    }
  }
  return data;
}

async function onLongformPlan() {
  const subject = $("longform-subject")?.value?.trim();
  if (!subject || subject.length < 2) {
    setLongformStatus("Ana konu en az 2 karakter olmali.", true);
    return;
  }
  if (!isLlmReady()) {
    setLongformStatus(llmBlockedReason() || "LLM hazir degil", true);
    return;
  }
  const btn = $("btn-longform-plan");
  if (btn) btn.disabled = true;
  setLongformStatus("Bolumler planlaniyor (LLM)...");
  startPipeline("long", "longformPlan", "Bolum plani", "Ana konu analiz ediliyor");
  setPipelineStep("long", 0, "Nis ve konu inceleniyor");
  try {
    setPipelineStep("long", 1, "LLM bolum basliklari yaziyor");
    const res = await fetch("/api/longform/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject,
        niche: $("longform-niche")?.value || "genel",
        chapter_count: 11,
      }),
    });
    const data = await readApiJson(res);
    if (!res.ok) throw apiError(data, "Plan basarisiz");
    longformChapters = (data.chapters || []).map((t) => normalizeLongformChapter(t));
    renderLongformChapters();
    completePipeline("long", `${longformChapters.length} bolum planlandi`);
    setLongformStatus(
      `${longformChapters.length} bolum planlandi — dusunme panelinde yonlendir, sonra uret.`
    );
    const panel = $("longform-think-panel");
    panel?.classList.remove("hidden");
    panel?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    void onLongformThink();
  } catch (e) {
    failPipeline("long", e.message || "Plan basarisiz");
    setLongformStatus(e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

let lastLongformThink = null;
let longformThinkQuestions = [];
let longformThinkAnswers = {};
let longformThinkLocks = {};

function setLongformThinkStatus(msg, isError = false) {
  const el = $("longform-think-status");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("err", !!isError);
}

function lockThinkQuestion(qid) {
  longformThinkLocks[qid] = true;
  const card = $("longform-think-body")?.querySelector(`.think-question[data-qid="${qid}"]`);
  if (!card) return;
  card.classList.add("think-locked");
  card.querySelectorAll("input").forEach((inp) => {
    inp.disabled = true;
  });
  if (!card.querySelector(".think-unlock")) {
    const unlock = document.createElement("button");
    unlock.type = "button";
    unlock.className = "btn-ghost btn-sm think-unlock";
    unlock.textContent = "Degistir";
    unlock.addEventListener("click", () => unlockThinkQuestion(qid));
    card.appendChild(unlock);
  }
}

function unlockThinkQuestion(qid) {
  longformThinkLocks[qid] = false;
  const card = $("longform-think-body")?.querySelector(`.think-question[data-qid="${qid}"]`);
  if (!card) return;
  card.classList.remove("think-locked");
  card.querySelectorAll("input").forEach((inp) => {
    inp.disabled = false;
  });
  card.querySelector(".think-unlock")?.remove();
  updateThinkPlanButtonState();
}

function updateThinkPlanButtonState() {
  const planBtn = $("btn-longform-think-plan");
  if (!planBtn) return;
  const answered = longformThinkQuestions.some((q) => {
    const ans = longformThinkAnswers[q.id] || { picks: [], own: "" };
    return (ans.picks && ans.picks.length) || (ans.own || "").trim();
  });
  planBtn.disabled = !longformThinkQuestions.length || !answered;
}

function renderLongformThinkQuestions() {
  const body = $("longform-think-body");
  if (!body) return;
  if (!longformThinkQuestions.length) {
    body.innerHTML =
      '<p class="hint">Once <strong>Bolumleri planla</strong> deyin; taslak gelince burada sorular acilir. Her soruda tek secenek.</p>';
    return;
  }
  body.innerHTML = longformThinkQuestions
    .map((q) => {
      const ans = longformThinkAnswers[q.id] || { picks: [], own: "" };
      const locked = !!longformThinkLocks[q.id];
      const opts = (q.options || [])
        .map((opt, oi) => {
          const checked = ans.picks.includes(opt) ? "checked" : "";
          return `<label class="think-opt">
            <input type="radio" name="think-${q.id}" value="${escapeHtml(opt)}" data-qid="${q.id}" data-opt-idx="${oi}" ${checked} ${locked ? "disabled" : ""} />
            <span>${escapeHtml(opt)}</span>
          </label>`;
        })
        .join("");
      return `<div class="think-question${locked ? " think-locked" : ""}" data-qid="${q.id}">
        <p class="think-question-text">${escapeHtml(q.question)} <span class="think-multi-hint">(tek secim)</span></p>
        <div class="think-opts">${opts}</div>
        <input type="text" class="think-own" data-qid="${q.id}" placeholder="Ya da kendin yaz…" value="${escapeHtml(ans.own || "")}" ${locked ? "disabled" : ""} />
        ${locked ? '<button type="button" class="btn-ghost btn-sm think-unlock" data-qid="' + q.id + '">Degistir</button>' : ""}
      </div>`;
    })
    .join("");

  body.querySelectorAll(".think-opt input").forEach((el) => {
    el.addEventListener("change", () => {
      const qid = el.dataset.qid;
      if (longformThinkLocks[qid]) return;
      if (!el.checked) return;
      longformThinkAnswers[qid] = { picks: [el.value], own: "" };
      const own = body.querySelector(`.think-own[data-qid="${qid}"]`);
      if (own) own.value = "";
      lockThinkQuestion(qid);
      updateThinkPlanButtonState();
    });
  });
  body.querySelectorAll(".think-own").forEach((el) => {
    const commitOwn = () => {
      const qid = el.dataset.qid;
      if (longformThinkLocks[qid]) return;
      const own = (el.value || "").trim();
      if (!own) return;
      longformThinkAnswers[qid] = { picks: [], own };
      body.querySelectorAll(`input[name="think-${qid}"]`).forEach((r) => {
        r.checked = false;
      });
      lockThinkQuestion(qid);
      updateThinkPlanButtonState();
    };
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        commitOwn();
      }
    });
    el.addEventListener("blur", () => commitOwn());
  });
  body.querySelectorAll(".think-unlock").forEach((btn) => {
    btn.addEventListener("click", () => unlockThinkQuestion(btn.dataset.qid));
  });
  updateThinkPlanButtonState();
}

function composeThinkNote() {
  const parts = [];
  for (const q of longformThinkQuestions) {
    const ans = longformThinkAnswers[q.id] || { picks: [], own: "" };
    const vals = [...(ans.picks || [])];
    if ((ans.own || "").trim()) vals.push(ans.own.trim());
    if (vals.length) parts.push(`${q.question} -> ${vals.join(", ")}`);
  }
  const extra = ($("longform-think-note")?.value || "").trim();
  if (extra) parts.push(`Ek not: ${extra}`);
  return parts.join("\n");
}

function renderLongformThink(plan) {
  const body = $("longform-think-body");
  if (!body) return;
  renderLongformThinkQuestions();
  if (!plan) return;
  const section = (title, items) => {
    const list = (items || []).filter(Boolean);
    if (!list.length) return "";
    return `<div class="longform-think-section">
      <h4>${escapeHtml(title)}</h4>
      <ul>${list.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>
    </div>`;
  };
  const line = (title, text) => {
    const t = (text || "").trim();
    if (!t) return "";
    return `<div class="longform-think-section">
      <h4>${escapeHtml(title)}</h4>
      <p>${escapeHtml(t)}</p>
    </div>`;
  };
  const chapters = plan.chapters || [];
  const chapterHtml = chapters.length
    ? `<div class="longform-think-section">
        <h4>Guncellenen bolumler (${chapters.length})</h4>
        <ol class="longform-think-chapters">${chapters
          .map((c) => `<li>${escapeHtml(c)}</li>`)
          .join("")}</ol>
      </div>`
    : "";
  const planHtml =
    line("Odak", plan.summary) +
    section("Acilar / yaklasimlar", plan.angles) +
    section("Hook fikirleri", plan.hooks) +
    section("Islenecek noktalar", plan.key_points) +
    line("Ton onerisi", plan.tone) +
    chapterHtml;
  const wrap = document.createElement("div");
  wrap.className = "longform-think-plan";
  wrap.innerHTML =
    '<div class="longform-think-plan-sep">Dusunme sonucu</div>' +
    (planHtml ||
      '<p class="hint">Plan bos dondu — cevaplari degistirip tekrar deneyin.</p>');
  body.appendChild(wrap);
}

function setLongformThinkBusy(busy) {
  ["btn-longform-think-again", "btn-longform-think-plan", "btn-longform-plan", "btn-longform-think-open"].forEach(
    (id) => {
      const b = $(id);
      if (b) b.disabled = busy;
    }
  );
  if (!busy) updateThinkPlanButtonState();
}

async function onLongformThink() {
  const subject = $("longform-subject")?.value?.trim();
  if (!subject || subject.length < 2) {
    setLongformThinkStatus("Once ana konu yazin (en az 2 karakter).", true);
    $("longform-think-panel")?.classList.remove("hidden");
    return;
  }
  if (!isLlmReady()) {
    setLongformThinkStatus(llmBlockedReason() || "LLM hazir degil", true);
    return;
  }
  const panel = $("longform-think-panel");
  if (panel) {
    panel.classList.remove("hidden");
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  lastLongformThink = null;
  setLongformThinkBusy(true);
  setLongformThinkStatus("Sorular hazirlaniyor…");
  try {
    const draft = longformChapters.map((c) => c.title).filter(Boolean);
    const res = await fetch("/api/longform/plan-questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject,
        niche: $("longform-niche")?.value || "genel",
        draft_chapters: draft,
      }),
    });
    const data = await readApiJson(res);
    if (!res.ok) throw apiError(data, "Sorular uretilemedi");
    longformThinkQuestions = (data.questions || []).map((q) => ({
      ...q,
      allow_multiple: false,
    }));
    longformThinkAnswers = {};
    longformThinkLocks = {};
    renderLongformThinkQuestions();
    setLongformThinkStatus(
      longformThinkQuestions.length
        ? "Her soruda tek secenek isaretle (veya kendin yaz); sonra asagidaki «Dusun»e bas."
        : "Soru gelmedi — tekrar deneyin.",
      !longformThinkQuestions.length
    );
  } catch (e) {
    setLongformThinkStatus(e.message || "Sorular uretilemedi", true);
  } finally {
    setLongformThinkBusy(false);
  }
}

async function onLongformThinkPlan() {
  const subject = $("longform-subject")?.value?.trim();
  if (!subject || subject.length < 2) {
    setLongformThinkStatus("Once ana konu yazin.", true);
    return;
  }
  if (!isLlmReady()) {
    setLongformThinkStatus(llmBlockedReason() || "LLM hazir degil", true);
    return;
  }
  const note = composeThinkNote();
  if (!note.trim()) {
    setLongformThinkStatus("En az bir soruyu cevaplayin.", true);
    return;
  }
  setLongformThinkBusy(true);
  setLongformThinkStatus("Cevaplarina gore plan duzenleniyor…");
  try {
    const priorChapters = longformChapters.map((c) => c.title).filter(Boolean);
    const res = await fetch("/api/longform/brainstorm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject,
        niche: $("longform-niche")?.value || "genel",
        note,
        prior: {
          chapters: priorChapters,
          ...(lastLongformThink || {}),
        },
      }),
    });
    const data = await readApiJson(res);
    if (!res.ok) throw apiError(data, "Plan olusturulamadi");
    lastLongformThink = data;
    renderLongformThink(data);
    applyLongformThinkChapters();
    setLongformThinkStatus(
      "Plan guncellendi ve bolumlere uygulandi — asagida duzenleyip uretebilirsiniz."
    );
  } catch (e) {
    setLongformThinkStatus(e.message || "Plan olusturulamadi", true);
  } finally {
    setLongformThinkBusy(false);
  }
}

function applyLongformThinkChapters() {
  const chapters = lastLongformThink?.chapters || [];
  if (!chapters.length) {
    setLongformThinkStatus("Uygulanacak bolum yok.", true);
    return;
  }
  longformChapters = chapters.map((t) => normalizeLongformChapter(t));
  renderLongformChapters();
  setLongformStatus(`${chapters.length} alt baslik dusunme panelinden guncellendi.`);
}

async function onLongformGenerate() {
  const main = $("longform-subject")?.value?.trim();
  if (!main || main.length < 2) {
    setLongformStatus("Ana konu girin.", true);
    return;
  }
  const normalized = longformChapters.map(normalizeLongformChapter).filter((c) => c.title.length > 0);
  const chapters = normalized.map((c) => c.title);
  if (!chapters.length) {
    setLongformStatus("En az bir bolum gerekli.", true);
    return;
  }
  const scripts = normalized.map((c) => (c.script.length >= 10 ? c.script : null));
  const dualLang = !!$("longform-dual-language")?.checked;
  saveLastVoiceFromForm();
  const btn = $("btn-longform-generate");
  if (btn) btn.disabled = true;
  beginProduction("longform");
  archivedLongformTasks.clear();
  setLongformStatus(
    dualLang
      ? "Tek paket uretiliyor: TR ses + altyazi + gorseller, sonra EN..."
      : "Tek paket uretiliyor: ses + altyazi + gorseller..."
  );
  $("longform-progress-wrap")?.classList.remove("hidden");
  startPipeline("long", "longformProduce", "Montajsiz paket", "Senaryo hazirlaniyor");
  setPipelineStep("long", 0, "Alt basliklardan senaryo birlestiriliyor");

  const tts = $("tts-engine")?.value || "edge";
  const body = {
    main_subject: main,
    chapters,
    scripts: scripts.some((s) => s) ? scripts : null,
    platform: $("longform-platform")?.value || "youtube",
    video_aspect: getLongformAspect(),
    video_source: $("longform-source")?.value || "pexels",
    production_language: dualLang ? "tr" : $("production-lang")?.value || "tr",
    dual_language: dualLang,
    tts_engine: tts,
    tts_provider: tts,
    niche: $("longform-niche")?.value || "genel",
    edge_voice: formEdgeVoice(),
    dual_llm: !!($("dual-llm")?.checked),
    editor_web_verify: !!($("editor-web-verify")?.checked),
    strengthen_hook: !!($("strengthen-hook")?.checked),
    writer_model: currentWriterModel() || null,
    editor_model: currentEditorModel() || null,
    rvc_voice: formRvcVoice(),
    rvc_pitch: Number($("rvc-pitch")?.value || 0),
    rvc_index_rate: Number($("rvc-index-rate")?.value || 1),
    voice_rate: formVoiceRate(),
    bgm_mode: "none",
    bgm_track: null,
    bgm_volume: 0,
    outro_id: ($("outro")?.value || "").trim() || null,
    video_clip_duration: getLongformClipDuration(),
    subtitle_style: buildLongformSubtitleStylePayload(),
    auto_retry_failed: !!$("longform-auto-retry")?.checked,
    auto_retry_rounds: 2,
    use_lang_preset: false,
    think_guidance: composeThinkNote(),
  };

  try {
    const res = await fetch("/api/longform/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: generateAbortController?.signal,
    });
    const data = await readApiJson(res);
    if (!res.ok) throw apiError(data, "Uzun video baslatilamadi");
    currentLongformId = data.longform_id;
    focusOutputJob(data.longform_id, "longform");
    setLongformStatus(
      dualLang
        ? `Kuyruk: ${data.total} bolum (TR+EN) — ${data.position}. sira`
        : `Kuyruk: ${data.total} bolum — ${data.position}. sira`
    );
    pushQueueNotification(
      dualLang
        ? `Uzun video kuyruga eklendi (${data.total} bolum, TR+EN)`
        : `Uzun video kuyruga eklendi (${data.total} bolum)`
    );
    startQueuePolling();
  } catch (e) {
    if (!isProductionCancelled()) {
      failPipeline("long", e.message || "Uzun video basarisiz");
      setLongformStatus(e.message, true);
    }
    updateLongformGenerateButton();
    if (productionMode === "longform") endProduction();
  }
}

async function onLongformRetry() {
  if (!currentLongformId) {
    setLongformStatus("Tekrar uretilecek gorev yok.", true);
    return;
  }
  const btn = $("btn-longform-retry");
  if (btn) btn.disabled = true;
  beginProduction("longform");
  $("longform-retry-row")?.classList.add("hidden");
  setLongformStatus("Basarisiz bolumler yeniden uretiliyor...");
  startPipeline("long", "longformProduce", "Uzun video — tekrar", "Hatali bolumler yeniden deneniyor");
  try {
    const statusRes = await fetch(`/api/longform/${currentLongformId}`);
    const statusData = await readApiJson(statusRes);
    if (statusRes.ok) {
      clearLongformArchiveKeysForRetry(
        (statusData.chapters || []).filter((ch) => ch.state === -1)
      );
    }
    const res = await fetch(`/api/longform/${currentLongformId}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        auto_retry_failed: !!$("longform-auto-retry")?.checked,
        auto_retry_rounds: 2,
      }),
      signal: generateAbortController?.signal,
    });
    const data = await readApiJson(res);
    if (!res.ok) throw apiError(data, "Tekrar uretim baslatilamadi");
    setLongformStatus(`${data.retrying || "?"} bolum kaldigi yerden — ${data.position || 1}. sira`);
    $("batch-progress-wrap")?.classList.remove("hidden");
    startQueuePolling();
  } catch (e) {
    if (!isProductionCancelled()) {
      failPipeline("long", e.message || "Tekrar uretim basarisiz");
      setLongformStatus(e.message, true);
    }
    updateLongformRetryUi({ failed: 1, chapters: [] });
    if (productionMode === "longform") endProduction();
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function onBatchGenerate() {
  const topics = getBatchTopics();
  if (!topics.length) {
    setStatus("En az bir konu ekleyin.", true);
    return;
  }
  const dualLang = !!$("dual-language")?.checked;
  const btn = $("btn-generate");
  btn.disabled = true;
  beginProduction("batch");
  archivedBatchTasks.clear();
  const [dl1, dl2] = dualLangCodes();
  setStatus(dualLang ? `Seri uretim baslatiliyor (her konu ${dl1} + ${dl2})...` : "Seri uretim baslatiliyor...");
  $("batch-progress-wrap")?.classList.remove("hidden");
  startPipeline(
    "short",
    "videoEngine",
    dualLang ? "Seri uretim (cift dil)" : "Seri uretim",
    "Ilk konu hazirlaniyor"
  );
  setPipelineStep("short", 0, "Senaryo asamasi");

  const tts = $("tts-engine")?.value || "edge";
  void tts;

  try {
    const data = await enqueueBatchProduction(topics);
    setStatus(
      dualLang
        ? `Kuyruk: seri (cift dil) ${data.total} konu — ${data.position}. sira`
        : `Kuyruk: seri ${data.total} video — ${data.position}. sira`
    );
  } catch (e) {
    if (!isProductionCancelled()) {
      failPipeline("short", e.message || "Seri uretim basarisiz");
      setStatus(e.message, true);
    }
    btn.disabled = !engineReady || !isLlmReady();
    if (productionMode === "batch") endProduction();
  }
}

async function pollUntilComplete(taskId, onProgress, maxMs = 45 * 60 * 1000) {
  const started = Date.now();
  let lastPct = -1;
  let stuckAt = Date.now();
  while (true) {
    if (isProductionCancelled()) {
      throw new Error("Uretim durduruldu");
    }
    if (Date.now() - started > maxMs) {
      throw new Error("Uretim zaman asimi (45 dk). Motor takilmis olabilir — AkiFactory.bat ile yeniden acin.");
    }
    const t = await pollTask(taskId);
    const pct = Math.min(100, Number(t.progress) || 0);
    if (pct !== lastPct) {
      lastPct = pct;
      stuckAt = Date.now();
    } else if (Date.now() - stuckAt > 8 * 60 * 1000) {
      const phase =
        pct >= 50
          ? "video montaji (klipler birlestiriliyor; cift dilde 2/2 EN adimi)"
          : "uretim";
      throw new Error(
        `${phase} ${pct}% adiminda takildi (8+ dk). AkiFactory.bat ile motoru yeniden acin; .aki_engine.log dosyasina bakin.`
      );
    }
    const label = t.step || t.state_label || `${pct}%`;
    const elapsedLbl =
      t.production_elapsed_sec > 0 ? ` · ${formatVcDuration(t.production_elapsed_sec)}` : "";
    if (onProgress) onProgress(pct, `${label}${elapsedLbl}`, t);
    if (t.state === 1) return t;
    if (t.state === -1) {
      throw new Error(t.failure_hint || t.error || "Uretim basarisiz");
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

async function cleanupVideoReuse(tag) {
  if (!tag) return;
  try {
    await fetch(`/api/video/reuse-cleanup/${encodeURIComponent(tag)}`, { method: "POST" });
  } catch {
    /* ignore */
  }
}

async function onDualLanguageGenerate(subject) {
  const btn = $("btn-generate");
  btn.disabled = true;
  beginProduction("dual");
  hideProgress();
  clearPreview();
  const preview = $("preview");
  if (preview) {
    preview.classList.add("empty");
    preview.innerHTML = "<p>Cift dil uretimi kuyruga eklendi...</p>";
  }

  const usedScript = syncScriptFromEditor();
  pendingScript = usedScript;
  const scripts = usedScript ? [usedScript] : undefined;

  try {
    startPipeline("short", "videoEngine", "Cift dil uretimi", subject);
    const [l1, l2] = dualLangCodes();
    setPipelineStep("short", 0, `Kuyruk — ${l1} sonra ${l2}`);
    const data = await enqueueBatchProduction([subject], { scripts, dualLang: true });
    setStatus(`Kuyruk: cift dil video — ${data.position}. sira`);
  } catch (e) {
    if (!isProductionCancelled()) {
      failPipeline("short", e.message || "Cift dil uretim basarisiz");
      setStatus(e.message || "Cift dil uretim basarisiz", true);
    }
    if (productionMode === "dual") endProduction();
  } finally {
    btn.disabled = !engineReady || !isLlmReady();
  }
}

async function onGenerate() {
  if ($("batch-mode")?.checked) {
    return onBatchGenerate();
  }

  const subject = $("subject")?.value.trim();
  if (subject.length < 2) {
    setStatus("En az 2 karakterlik bir konu yaz.", true);
    return;
  }
  if ($("bgm-mode")?.value === "custom" && !($("bgm-track")?.value || "").trim()) {
    setStatus(
      `Parca sec modu — listeden bir muzik sec veya data/bgm/${currentNicheId()}/ klasorune MP3 koy.`,
      true
    );
    return;
  }
  if ($("dual-language")?.checked) {
    return onDualLanguageGenerate(subject);
  }

  const btn = $("btn-generate");
  btn.disabled = true;
  beginProduction("single");
  hideProgress();
  clearPreview();
  const preview = $("preview");
  if (preview) {
    preview.classList.add("empty");
    preview.innerHTML = "<p>Uretim kuyruguna eklendi...</p>";
  }

  syncScriptFromEditor();
  const usedScript = syncScriptFromEditor();
  const scripts = usedScript ? [usedScript] : undefined;
  pendingScript = usedScript;

  startPipeline("short", "videoEngine", "Video uretimi", subject);
  setPipelineStep("short", 0, usedScript ? "Senaryo hazir — kuyruk" : "Senaryo + video — kuyruk");

  try {
    const data = await enqueueBatchProduction([subject], { scripts, dualLang: false });
    setStatus(`Kuyruk: kisa video — ${data.position}. sira`);
    loadHistory();
  } catch (e) {
    if (isProductionCancelled()) {
      hideProgress();
      return;
    }
    failPipeline("short", friendlyApiError(e));
    setStatus(friendlyApiError(e), true);
    endProduction();
  } finally {
    btn.disabled = !engineReady || !isLlmReady();
  }
}

function friendlyApiError(e) {
  const msg = e?.message || String(e ?? "Bilinmeyen hata");
  if (/Unexpected token.*JSON/i.test(msg) || /is not valid JSON/i.test(msg)) {
    return "Sunucu beklenmeyen yanit verdi. AkiFactory.bat ile uygulamayi kapatip yeniden acin.";
  }
  return msg;
}

let scriptLoadingTimer = null;

function openScriptModal() {
  $("script-modal")?.classList.remove("hidden");
}

function closeScriptModal() {
  $("script-modal")?.classList.add("hidden");
  setScriptLoading(false);
}

function setScriptLoading(loading, message = "") {
  const wrap = $("script-editor-wrap");
  const overlay = $("script-loading");
  const ta = $("script-preview-text");
  const textEl = $("script-loading-text");
  const subEl = $("script-loading-sub");
  const dual = !!$("dual-llm")?.checked;
  const editorBtn = $("btn-editor-script");
  const useBtn = $("btn-use-script");

  if (!loading && scriptLoadingTimer) {
    clearTimeout(scriptLoadingTimer);
    scriptLoadingTimer = null;
  }

  wrap?.classList.toggle("is-loading", loading);
  overlay?.classList.toggle("hidden", !loading);
  if (overlay) overlay.setAttribute("aria-busy", loading ? "true" : "false");

  if (ta) ta.disabled = loading;
  if (textEl) {
    textEl.textContent = message || (dual ? "Cift LLM senaryo hazirliyor..." : "Senaryo uretiliyor...");
  }
  if (subEl) {
    subEl.textContent = dual
      ? "Once yazar LLM taslak yazar, sonra editor modeli duzenler — 30-90 sn sürebilir."
      : "Ollama yanit bekleniyor...";
  }
  if (editorBtn) editorBtn.disabled = loading;
  if (useBtn) useBtn.disabled = loading;
}

function updateScriptMetaFromText(text) {
  const meta = $("script-meta");
  if (!meta) return;
  const t = (text || "").trim();
  if (!t) {
    meta.textContent = "";
    return;
  }
  const chars = t.length;
  const sec = Math.max(5, Math.round(chars / 12));
  meta.textContent = `${chars} karakter · ~${sec} sn`;
}

function renderScriptPreview(data) {
  const ta = $("script-preview-text");
  const hook = $("script-hook-preview");
  const script = data.script || "";
  if (ta) ta.value = script;
  updateScriptMetaFromText(script);
  const meta = $("script-meta");
  if (meta && data.dual_llm && data.draft_script) {
    meta.textContent += ` · Cift LLM (${data.writer_model || "?"} → ${data.editor_model || "?"})`;
    if (data.web_sources > 0) {
      meta.textContent += ` · Web dogrulama (${data.web_sources} kaynak)`;
    } else if (data.web_verified) {
      meta.textContent += " · Web dogrulama";
    }
  }
  if (hook) {
    const h = data.hook || "";
    hook.innerHTML = h
      ? `<strong>Hook:</strong> ${escapeHtml(h)}${
          data.hook_strong ? "" : data.hook_cliche ? " (klise — yeniden yazildi)" : " (zayif — guclendirildi)"
        }`
      : "";
  }
}

function openScriptEditor() {
  const ta = $("script-preview-text");
  const hook = $("script-hook-preview");
  if (ta) {
    if (!ta.value.trim() && pendingScript) ta.value = pendingScript;
    updateScriptMetaFromText(ta.value);
  }
  if (hook && !ta?.value.trim()) hook.innerHTML = "";
  openScriptModal();
  ta?.focus();
}

async function fetchScriptPreview() {
  const subject = $("subject")?.value.trim();
  if (!subject || subject.length < 2) {
    setStatus("Once konu yaz.", true);
    return null;
  }
  const res = await fetch("/api/preview/script", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      video_subject: subject,
      platform: $("platform")?.value || "tiktok",
      production_language: $("production-lang")?.value || "tr",
      niche: $("niche")?.value || "genel",
      strengthen_hook: !!$("strengthen-hook")?.checked,
      dual_llm: !!($("dual-llm")?.checked),
      editor_web_verify: !!($("editor-web-verify")?.checked),
      writer_model: currentWriterModel() || null,
      editor_model: currentEditorModel() || null,
    }),
  });
  const data = await readApiJson(res);
  if (!res.ok) throw apiError(data, "Senaryo uretilemedi");
  return data;
}

$("btn-preview-script")?.addEventListener("click", () => {
  openScriptEditor();
});

$("script-preview-text")?.addEventListener("input", (e) => {
  updateScriptMetaFromText(e.target.value);
});

$("btn-editor-script")?.addEventListener("click", async () => {
  const btn = $("btn-editor-script");
  const dual = !!$("dual-llm")?.checked;
  try {
    openScriptModal();
    startPipeline("short", dual ? "scriptDual" : "scriptSimple", "Senaryo uretimi", subjectLabel());
    setPipelineStep("short", 0, dual ? "Yazar LLM calisiyor" : "Ollama senaryo yaziyor");
    setScriptLoading(true, dual ? "Yazar LLM calisiyor..." : "Senaryo uretiliyor...");
    const meta = $("script-meta");
    if (meta) meta.textContent = "Editor ile uretim devam ediyor...";
    if (btn) btn.disabled = true;
    setStatus("Editor senaryo uretiyor...");

    if (dual) {
      scriptLoadingTimer = setTimeout(() => {
        if ($("script-editor-wrap")?.classList.contains("is-loading")) {
          setScriptLoading(true, "Editor modeli duzenliyor...");
          setPipelineStep("short", 1, "Editor modeli duzenliyor");
        }
      }, 12000);
      setTimeout(() => {
        if ($("script-editor-wrap")?.classList.contains("is-loading") && $("editor-web-verify")?.checked) {
          setScriptLoading(true, "Editor web kaynaklarini kontrol ediyor...");
          setPipelineStep("short", 1, "Web dogrulama + duzeltme");
        }
      }, 28000);
    }

    const data = await fetchScriptPreview();
    if (!data) return;
    renderScriptPreview(data);
    completePipeline("short", "Senaryo hazir — videoyu uretebilirsin");
    setStatus("Senaryo hazir — duzenleyebilir veya videoyu uretebilirsin.");
  } catch (e) {
    failPipeline("short", e.message || "Senaryo uretilemedi");
    setStatus(e.message, true);
    const meta = $("script-meta");
    if (meta) meta.textContent = "";
  } finally {
    setScriptLoading(false);
    if (btn) btn.disabled = false;
  }
});

function subjectLabel() {
  return ($("subject")?.value?.trim() || "Konu").slice(0, 60);
}

$("btn-use-script")?.addEventListener("click", () => {
  pendingScript = $("script-preview-text")?.value.trim() || "";
  closeScriptModal();
  if (!$("batch-mode")?.checked) onGenerate();
  else setStatus("Seri modda onizleme senaryosu ilk konuya uygulanir.");
});

document.querySelectorAll("[data-close-modal]").forEach((el) => {
  el.addEventListener("click", closeScriptModal);
});

$("btn-gallery-detail-close")?.addEventListener("click", closeGalleryDetailModal);
$("btn-gallery-open-folder")?.addEventListener("click", async () => {
  if (!galleryDetailItem?.id) return;
  try {
    if (isLongformGalleryItem(galleryDetailItem) || galleryViewMode === "long") {
      await openLongformGalleryFolder(galleryDetailItem.id);
    } else {
      await openGalleryEntryFolder(galleryDetailItem.id);
      showToast("Klasor acildi");
    }
  } catch (e) {
    showToast(e.message || "Klasor acilamadi", 5000);
  }
});
document.querySelectorAll("[data-close-gallery-detail]").forEach((el) => {
  el.addEventListener("click", closeGalleryDetailModal);
});
$("btn-gallery-detail-copy-all")?.addEventListener("click", (e) => {
  if (!galleryDetailItem) return;
  copyText(galleryDetailAllText(galleryDetailItem), e.currentTarget);
});

$("dual-language")?.addEventListener("change", updateDualLanguageUi);
$("dual-second-lang")?.addEventListener("change", () => {
  const v = $("dual-second-lang")?.value;
  if (v) localStorage.setItem(DUAL_SECOND_LANG_KEY, v);
  updateDualLanguageUi();
});

$("btn-suggest-topics")?.addEventListener("click", async () => {
  try {
    startPipeline("short", "topicSuggest", "Konu onerileri", "LLM calisiyor");
    setPipelineStep("short", 0, "Nis profili okunuyor");
    setStatus("Konu onerileri aliniyor...");
    setPipelineStep("short", 1, "Konular uretiliyor");
    const niche = $("niche")?.value || "tarih_gizem";
    const suggestCount = niche === "seyahat" ? 1 : 5;
    const r = await fetch("/api/suggest/topics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ niche, count: suggestCount }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Oneri alinamadi");
    let topics = data.topics || [];
    if (!topics.length) {
      failPipeline("short", "Oneri uretilemedi");
      setStatus("Oneri uretilemedi.", true);
      return;
    }
    if ($("batch-mode")?.checked) {
      const existing = getBatchTopics().map((t) => t.trim().toLowerCase()).filter(Boolean);
      topics = topics.filter((t) => !existing.includes(t.trim().toLowerCase()));
      if (!topics.length) {
        failPipeline("short", "Tum oneriler listede zaten var");
        setStatus("Bu nis icin yeni konu kalmadi — listedeki konulari uretin veya nisi degistirin.", true);
        return;
      }
      topics.forEach((t) => addBatchRow(t));
    } else {
      $("subject").value = topics[0];
    }
    const mem = data.memory;
    const memHint =
      mem && mem.produced > 0
        ? ` (${mem.produced} uretilmis konu haric tutuldu)`
        : "";
    completePipeline("short", niche === "seyahat" ? "Destinasyon onerildi" : `${topics.length} konu onerildi`);
    setStatus(
      niche === "seyahat"
        ? `Destinasyon onerildi${memHint}.`
        : `${topics.length} konu onerildi${memHint}.`
    );
    showToast(topics[0], 3000);
  } catch (e) {
    failPipeline("short", e.message || "Konu onerisi basarisiz");
    setStatus(e.message, true);
  }
});

$("history-filter")?.addEventListener("change", loadHistory);
$("btn-save-draft")?.addEventListener("click", saveCurrentDraft);
$("btn-save-longform-draft")?.addEventListener("click", saveLongformDraft);

let vcActiveId = null;
let vcLoadingTimer = null;

const VC_LOADING_STEPS = [
  "Ses dosyasi hazirlaniyor…",
  "RVC modeli yukleniyor…",
  "Ses karakteri donusturuluyor…",
  "Uzun kayitlar birkaç dakika surebilir…",
];

function setVcStatus(msg, isError = false) {
  const el = $("vc-status");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("error", !!isError);
}

function showVcPreviewLoading(fileName, voiceLabel) {
  const loading = $("vc-preview-loading");
  const idle = $("vc-preview-idle");
  const audio = $("vc-preview-audio");
  const dl = $("vc-download-link");
  if (loading) {
    loading.classList.remove("hidden");
    loading.setAttribute("aria-busy", "true");
  }
  if (idle) idle.classList.add("hidden");
  if (audio) {
    audio.pause();
    audio.removeAttribute("src");
  }
  if (dl) dl.classList.add("hidden");
  const sub = $("vc-loading-sub");
  if (sub) sub.textContent = `${fileName || "Kayit"} → ${voiceLabel || "RVC"}`;
  let step = 0;
  const textEl = $("vc-loading-text");
  if (textEl) textEl.textContent = VC_LOADING_STEPS[0];
  clearInterval(vcLoadingTimer);
  vcLoadingTimer = setInterval(() => {
    step = (step + 1) % VC_LOADING_STEPS.length;
    if (textEl) textEl.textContent = VC_LOADING_STEPS[step];
  }, 2800);
}

function hideVcPreviewLoading() {
  clearInterval(vcLoadingTimer);
  vcLoadingTimer = null;
  const loading = $("vc-preview-loading");
  const idle = $("vc-preview-idle");
  if (loading) {
    loading.classList.add("hidden");
    loading.setAttribute("aria-busy", "false");
  }
  if (idle) idle.classList.remove("hidden");
}

function vcRecommendedIndexRate(meta) {
  const idx = Number(meta?.index_rate);
  if (Number.isFinite(idx) && idx > 0 && idx < 0.99) return idx;
  return 0.75;
}

function updateVcFileHint(file) {
  const hint = $("vc-file-hint");
  if (!hint) return;
  if (!file) {
    hint.textContent = "WAV, MP3, M4A… (en fazla 80 MB)";
    return;
  }
  const mb = (file.size / (1024 * 1024)).toFixed(1);
  const ext = (file.name.split(".").pop() || "").toUpperCase();
  hint.textContent = `${file.name} · ${mb} MB · ${ext}`;
  const url = URL.createObjectURL(file);
  const probe = new Audio(url);
  probe.addEventListener(
    "loadedmetadata",
    () => {
      URL.revokeObjectURL(url);
      const dur = probe.duration;
      if (!Number.isFinite(dur) || dur <= 0) return;
      const extra =
        dur > 120
          ? " — uzun kayit, donusum birkaç dakika surebilir"
          : ext !== "WAV"
            ? " — en iyi sonuc icin WAV onerilir"
            : "";
      hint.textContent = `${file.name} · ${formatVcDuration(dur)} · ${mb} MB${extra}`;
    },
    { once: true }
  );
  probe.addEventListener("error", () => URL.revokeObjectURL(url), { once: true });
}

function updateVcRangeLabels() {
  const p = $("vc-pitch");
  const i = $("vc-index-rate");
  const pv = $("vc-pitch-val");
  const iv = $("vc-index-val");
  if (p && pv) pv.textContent = p.value;
  if (i && iv) iv.textContent = Number(i.value).toFixed(2);
}

function populateVcRvcVoices() {
  const sel = $("vc-rvc-voice");
  const hint = $("vc-rvc-hint");
  if (!sel) return;
  const voices = appConfig?.rvc_voices || [];
  if (!voices.length) {
    sel.innerHTML = `<option value="">RVC modeli yok</option>`;
    hint?.classList.remove("hidden");
    syncSelectUi(sel);
    return;
  }
  hint?.classList.add("hidden");
  const preferred =
    $("rvc-voice")?.value ||
    localStorage.getItem(RVC_VOICE_KEY) ||
    voices.find((v) => v.default)?.id ||
    voices[0].id;
  sel.innerHTML = voices
    .map((v) => `<option value="${escapeHtml(v.id)}">${escapeHtml(v.label)}</option>`)
    .join("");
  if (voices.some((v) => v.id === preferred)) sel.value = preferred;
  else sel.value = voices[0].id;
  const meta = voices.find((v) => v.id === sel.value);
  if (meta) {
    if ($("vc-pitch")) $("vc-pitch").value = String(meta.pitch ?? 0);
    if ($("vc-index-rate")) $("vc-index-rate").value = String(vcRecommendedIndexRate(meta));
    updateVcRangeLabels();
  }
  syncSelectUi(sel);
}

function formatVcDuration(sec) {
  const s = Number(sec) || 0;
  if (s < 60) return `${Math.round(s)} sn`;
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return r ? `${m} dk ${r} sn` : `${m} dk`;
}

function updatePreviewOutputMeta(sec, label = "") {
  const el = $("preview-output-meta");
  if (!el) return;
  const n = Number(sec) || 0;
  const parts = [];
  if (label) parts.push(`Son uretim: ${label}`);
  if (n > 0) parts.push(`Uretim suresi: ${formatVcDuration(n)}`);
  if (parts.length) {
    el.textContent = parts.join(" · ");
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

function formatVcDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("tr-TR", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function showVcPreview(item) {
  hideVcPreviewLoading();
  if (!item?.stream_url) return;
  vcActiveId = item.id;
  const audio = $("vc-preview-audio");
  const dl = $("vc-download-link");
  const meta = $("vc-preview-meta");
  if (audio) {
    audio.src = `${item.stream_url}?t=${Date.now()}`;
    audio.load();
  }
  if (dl) {
    dl.href = item.download_url || item.stream_url;
    dl.classList.remove("hidden");
  }
  if (meta) {
    meta.textContent = `${item.original_name || "Kayit"} → ${item.rvc_voice_label || item.rvc_voice} · ${formatVcDuration(item.duration_sec)} · ${item.size_mb || "?"} MB`;
  }
  document.querySelectorAll(".vc-history-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.id === item.id);
  });
}

function renderVcHistoryList(items) {
  const list = $("vc-history-list");
  if (!list) return;
  if (!items?.length) {
    list.innerHTML = `<li class="hint">Henuz kayit yok. Yukaridan ses yukleyip donustur.</li>`;
    return;
  }
  list.innerHTML = items
    .map((item) => {
      const title = escapeHtml(item.original_name || "Kayit");
      const voice = escapeHtml(item.rvc_voice_label || item.rvc_voice || "RVC");
      const when = escapeHtml(formatVcDate(item.created_at));
      const dur = formatVcDuration(item.duration_sec);
      return `<li class="vc-history-item${item.id === vcActiveId ? " active" : ""}" data-id="${escapeHtml(item.id)}">
        <p class="vc-history-title">${title}</p>
        <div class="vc-history-actions">
          <a class="btn-ghost btn-sm" href="${escapeHtml(item.download_url || "#")}" download title="Indir">↓</a>
          <button type="button" class="btn-ghost btn-sm vc-delete" data-id="${escapeHtml(item.id)}" title="Sil">×</button>
        </div>
        <p class="vc-history-meta">${voice} · ${dur} · ${when}</p>
      </li>`;
    })
    .join("");
}

async function loadVoiceConvertHistory() {
  const list = $("vc-history-list");
  if (list) list.innerHTML = `<li class="hint">Kayitlar yukleniyor…</li>`;
  try {
    const r = await fetchWithTimeout("/api/voice/convert?limit=50", {}, 15000);
    const data = await readApiJson(r);
    if (!r.ok) throw new Error(data.detail || data.error || "Liste alinamadi");
    const items = data.items || [];
    renderVcHistoryList(items);
    if (items.length && !vcActiveId) showVcPreview(items[0]);
    else if (vcActiveId) {
      const cur = items.find((x) => x.id === vcActiveId);
      if (cur) showVcPreview(cur);
    }
  } catch (e) {
    if (list) list.innerHTML = `<li class="hint error">${escapeHtml(e.message)}</li>`;
  }
}

async function runVoiceConvert() {
  const fileInput = $("vc-file");
  const file = fileInput?.files?.[0];
  const rvcVoice = $("vc-rvc-voice")?.value || "";
  if (!file) {
    setVcStatus("Once bir ses dosyasi sec.", true);
    return;
  }
  if (!rvcVoice) {
    setVcStatus("Hedef RVC sesi secin.", true);
    return;
  }
  if (!appConfig?.rvc_available) {
    setVcStatus("RVC kullanilamiyor. models/rvc/ klasorune model ekleyin.", true);
    return;
  }
  const btn = $("btn-vc-convert");
  if (btn) btn.disabled = true;
  const voiceMeta = (appConfig?.rvc_voices || []).find((v) => v.id === rvcVoice);
  const voiceLabel = voiceMeta?.label || rvcVoice;
  setVcStatus("Donusum suruyor…");
  showVcPreviewLoading(file.name, voiceLabel);
  try {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("rvc_voice", rvcVoice);
    fd.append("rvc_pitch", String($("vc-pitch")?.value || 0));
    fd.append("rvc_index_rate", String($("vc-index-rate")?.value || 1));
    const r = await fetchWithTimeout(
      "/api/voice/convert",
      { method: "POST", body: fd },
      600000
    );
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Donusum basarisiz");
    const item = data.item;
    showVcPreview(item);
    await loadVoiceConvertHistory();
    setVcStatus("Donusum tamamlandi.");
    showToast("Ses donusturuldu");
  } catch (e) {
    hideVcPreviewLoading();
    setVcStatus(e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

$("vc-file")?.addEventListener("change", () => {
  const file = $("vc-file")?.files?.[0];
  const hint = $("vc-file-hint");
  if (!hint) return;
  if (!file) {
    hint.textContent = "WAV, MP3, M4A… (en fazla 80 MB)";
    return;
  }
  const mb = (file.size / (1024 * 1024)).toFixed(1);
  hint.textContent = `${file.name} — ${mb} MB`;
});

$("vc-rvc-voice")?.addEventListener("change", () => {
  const meta = (appConfig?.rvc_voices || []).find((v) => v.id === $("vc-rvc-voice")?.value);
  if (meta) {
    if ($("vc-pitch")) $("vc-pitch").value = String(meta.pitch ?? 0);
    if ($("vc-index-rate")) $("vc-index-rate").value = String(vcRecommendedIndexRate(meta));
    updateVcRangeLabels();
  }
});
$("vc-file")?.addEventListener("change", () => {
  updateVcFileHint($("vc-file")?.files?.[0] || null);
});

$("vc-pitch")?.addEventListener("input", updateVcRangeLabels);
$("vc-index-rate")?.addEventListener("input", updateVcRangeLabels);

$("btn-vc-convert")?.addEventListener("click", () => void runVoiceConvert());
$("btn-vc-refresh-history")?.addEventListener("click", () => void loadVoiceConvertHistory());
$("btn-vc-refresh-models")?.addEventListener("click", async () => {
  await refreshRvcVoicesFromDisk({ silent: false });
  populateVcRvcVoices();
});

$("vc-history-list")?.addEventListener("click", async (e) => {
  const delBtn = e.target.closest(".vc-delete");
  if (delBtn) {
    e.stopPropagation();
    const id = delBtn.dataset.id;
    if (!id || !confirm("Bu kaydi sil?")) return;
    try {
      const r = await fetch(`/api/voice/convert/${id}`, { method: "DELETE" });
      const data = await readApiJson(r);
      if (!r.ok) throw apiError(data, "Silinemedi");
      if (vcActiveId === id) {
        vcActiveId = null;
        const audio = $("vc-preview-audio");
        if (audio) audio.removeAttribute("src");
        $("vc-download-link")?.classList.add("hidden");
        $("vc-preview-meta").textContent = "Kayit silindi.";
      }
      await loadVoiceConvertHistory();
      showToast("Kayit silindi");
    } catch (err) {
      showToast(err.message, 4000);
    }
    return;
  }
  const row = e.target.closest(".vc-history-item");
  if (!row?.dataset.id) return;
  const r = await fetchWithTimeout("/api/voice/convert?limit=50", {}, 15000);
  const data = await readApiJson(r);
  const item = (data.items || []).find((x) => x.id === row.dataset.id);
  if (item) showVcPreview(item);
});

function setWangpStatus(msg, isError = false) {
  const el = $("wangp-status");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("error", !!isError);
}

function fillWangpOutput(data) {
  const promptTa = $("wangp-prompt-out");
  const negTa = $("wangp-negative-out");
  const notesEl = $("wangp-notes-out");
  const batches = data.batches || [];
  const first = batches[0];
  const block = first?.prompt_block || data.prompt_block || (data.scenes || []).join("\n");
  if (promptTa) promptTa.value = block;
  const turLabel = $("wangp-prompt-tur-label");
  if (turLabel) {
    turLabel.textContent = first?.label
      ? `Ana prompt — ${first.label}`
      : batches.length > 1
        ? "Ana prompt — Tur 1"
        : "Ana prompt (sahneler)";
  }
  if (negTa) negTa.value = data.negative_prompt || first?.negative_prompt || "";
  if (notesEl) notesEl.textContent = data.wgp_notes || "H3 Studio kullanim notu uretilemedi.";
  $("btn-wangp-copy-prompt")?.toggleAttribute("disabled", !block);
  $("btn-wangp-copy-negative")?.toggleAttribute("disabled", !data.negative_prompt);

  const wrap = $("wangp-batches-wrap");
  const list = $("wangp-batches-out");
  const rest = batches.slice(1);
  if (wrap && list) {
    if (rest.length) {
      wrap.classList.remove("hidden");
      list.innerHTML = rest
        .map(
          (b, i) =>
            `<li class="fooocus-variant-item wangp-batch-item">
              <div class="wangp-batch-body">
                <strong>${escapeHtml(b.label || `Tur ${b.index || i + 2}`)}</strong>
                <pre class="wangp-batch-pre">${escapeHtml(b.prompt_block || "")}</pre>
              </div>
              <button type="button" class="btn-ghost btn-sm btn-wangp-copy-batch" data-batch="${i}">Kopyala</button>
            </li>`
        )
        .join("");
      list.querySelectorAll(".btn-wangp-copy-batch").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.dataset.batch);
          const batch = rest[idx];
          const text = batch?.prompt_block || "";
          copyText(text.trim(), btn);
        });
      });
    } else {
      wrap.classList.add("hidden");
      list.innerHTML = "";
    }
  }
}

$("btn-wangp-from-subject")?.addEventListener("click", () => {
  const subj = activeProduceSubject();
  if (!subj) {
    setWangpStatus("Uretim sekmesinde konu yok.", true);
    return;
  }
  $("wangp-topic").value = subj;
  const niche =
    activeProduceSubTab() === "long"
      ? $("longform-niche")?.value
      : $("niche")?.value;
  if (niche && $("wangp-niche")) $("wangp-niche").value = niche;
  setWangpStatus("Konu aktarildi.");
});

$("btn-wangp-generate")?.addEventListener("click", async () => {
  const topic = $("wangp-topic")?.value?.trim();
  if (!topic || topic.length < 2) {
    setWangpStatus("En az 2 karakterlik bir konu gir.", true);
    return;
  }
  if (!isLlmReady()) {
    setWangpStatus(llmBlockedReason() || "LLM hazir degil", true);
    return;
  }
  const btn = $("btn-wangp-generate");
  if (btn) btn.disabled = true;
  const batchCount = parseInt($("wangp-batch-count")?.value || "1", 10);
  setWangpStatus(
    batchCount > 1
      ? `${batchCount} tur H3 Studio promptu uretiliyor (her tur farkli SCENE)…`
      : "H3 Studio promptu uretiliyor…"
  );
  try {
    const r = await fetch("/api/wangp/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic,
        niche: $("wangp-niche")?.value || "tarih_gizem",
        scene_count: parseInt($("wangp-scene-count")?.value || "4", 10),
        batch_count: batchCount,
        style: $("wangp-style")?.value || "dark_mystery",
        line_mode: $("wangp-line-mode")?.value || "sliding_window",
        aspect: $("wangp-aspect")?.value || "9:16",
      }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Prompt uretilemedi");
    fillWangpOutput(data);
    const tur = data.batch_count || 1;
    const sahne = (data.scenes || []).length;
    setWangpStatus(
      tur > 1
        ? `${tur} tur, ${sahne} SCENE hazir — once ust kutuyu H3 Studio'da calistir, sonra diger turlere gec.`
        : `${sahne} SCENE senaryosu hazir. H3 Studio'ya yapistirabilirsin.`
    );
    showToast("H3 Studio promptu hazir");
  } catch (e) {
    setWangpStatus(e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
});

$("btn-wangp-copy-prompt")?.addEventListener("click", (e) => {
  const text = $("wangp-prompt-out")?.value || "";
  if (text) copyText(text, e.currentTarget);
});

$("btn-wangp-copy-negative")?.addEventListener("click", (e) => {
  const text = $("wangp-negative-out")?.value || "";
  if (text) copyText(text, e.currentTarget);
});

function setFooocusStatus(msg, isError = false) {
  const el = $("fooocus-status");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("error", !!isError);
}

function fillFooocusOutput(data) {
  const promptTa = $("fooocus-prompt-out");
  const negTa = $("fooocus-negative-out");
  const notesEl = $("fooocus-notes-out");
  const prompt = data.prompt || "";
  if (promptTa) promptTa.value = prompt;
  if (negTa) negTa.value = data.negative_prompt || "";
  if (notesEl) notesEl.textContent = data.fooocus_notes || "Qwen gorsel ayar onerisi uretilemedi.";
  $("btn-fooocus-copy-prompt")?.toggleAttribute("disabled", !prompt);
  $("btn-fooocus-copy-negative")?.toggleAttribute("disabled", !data.negative_prompt);
  const variants = data.variants || [];
  const wrap = $("fooocus-variants-wrap");
  const list = $("fooocus-variants-out");
  if (wrap && list) {
    if (variants.length) {
      wrap.classList.remove("hidden");
      list.innerHTML = variants
        .map(
          (v, i) =>
            `<li class="fooocus-variant-item">
              <p>${escapeHtml(v)}</p>
              <button type="button" class="btn-ghost btn-sm btn-fooocus-copy-variant" data-variant="${i}">Kopyala</button>
            </li>`
        )
        .join("");
      list.querySelectorAll(".btn-fooocus-copy-variant").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.dataset.variant);
          copyText(variants[idx] || "", btn);
        });
      });
    } else {
      wrap.classList.add("hidden");
      list.innerHTML = "";
    }
  }
}

$("btn-fooocus-from-subject")?.addEventListener("click", () => {
  const subj = activeProduceSubject();
  if (!subj) {
    setFooocusStatus("Uretim sekmesinde konu yok.", true);
    return;
  }
  $("fooocus-topic").value = subj;
  const niche =
    activeProduceSubTab() === "long"
      ? $("longform-niche")?.value
      : $("niche")?.value;
  if (niche && $("fooocus-niche")) $("fooocus-niche").value = niche;
  syncSelectUi($("fooocus-niche"));
  setFooocusStatus("Konu aktarildi.");
});

$("btn-fooocus-generate")?.addEventListener("click", async () => {
  const topic = $("fooocus-topic")?.value?.trim();
  if (!topic || topic.length < 2) {
    setFooocusStatus("En az 2 karakterlik bir konu gir.", true);
    return;
  }
  if (!isLlmReady()) {
    setFooocusStatus(llmBlockedReason() || "LLM hazir degil", true);
    return;
  }
  const btn = $("btn-fooocus-generate");
  if (btn) btn.disabled = true;
  setFooocusStatus("Qwen gorsel promptu uretiliyor…");
  try {
    const r = await fetch("/api/fooocus/prompt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topic,
        niche: $("fooocus-niche")?.value || "tarih_gizem",
        style: $("fooocus-style")?.value || "photorealistic",
        aspect: $("fooocus-aspect")?.value || "9:16",
        purpose: $("fooocus-purpose")?.value || "thumbnail",
        variant_count: parseInt($("fooocus-variant-count")?.value || "1", 10),
      }),
    });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Prompt uretilemedi");
    fillFooocusOutput(data);
    const alt = (data.variants || []).length;
    setFooocusStatus(
      alt ? `Prompt hazir (+${alt} alternatif). Qwen prompt kutusuna yapistir.` : "Qwen gorsel promptu hazir."
    );
    showToast("Qwen gorsel promptu hazir");
  } catch (e) {
    setFooocusStatus(e.message, true);
  } finally {
    if (btn) btn.disabled = false;
  }
});

$("btn-fooocus-copy-prompt")?.addEventListener("click", (e) => {
  const text = $("fooocus-prompt-out")?.value || "";
  if (text) copyText(text, e.currentTarget);
});

$("btn-fooocus-copy-negative")?.addEventListener("click", (e) => {
  const text = $("fooocus-negative-out")?.value || "";
  if (text) copyText(text, e.currentTarget);
});

$("btn-publish-copy-wangp")?.addEventListener("click", (e) => {
  const text = $("publish-wangp-prompt")?.value || "";
  if (text) copyText(text, e.currentTarget);
});

$("btn-publish-copy-wangp-neg")?.addEventListener("click", (e) => {
  const text = $("publish-wangp-negative")?.value || "";
  if (text) copyText(text, e.currentTarget);
});

$("gallery-filter-platform")?.addEventListener("change", () => {
  if (galleryViewMode === "long") void loadLongformGallery();
  else void loadGallery();
});
$("gallery-filter-niche")?.addEventListener("change", () => {
  if (galleryViewMode === "long") void loadLongformGallery();
  else void loadGallery();
});
$("btn-gallery-select-all")?.addEventListener("click", () => toggleGallerySelectAll());
$("btn-gallery-bulk-delete")?.addEventListener("click", () => void bulkDeleteGallerySelection());

$("analyze-gallery-select")?.addEventListener("change", () => {
  updateAnalyzeVideoPreview();
  void loadAnalyzeHistory();
});
$("analyze-image-files")?.addEventListener("change", updateAnalyzeImagePreview);
$("analyze-vision-model")?.addEventListener("change", () => {
  const v = $("analyze-vision-model")?.value;
  if (v) localStorage.setItem(ANALYZE_VISION_KEY, v);
});
$("btn-analyze-run")?.addEventListener("click", () => void runAnalyze());
$("btn-analyze-refresh-videos")?.addEventListener("click", () => void loadAnalyzeGalleryOptions());
$("btn-analyze-refresh-history")?.addEventListener("click", () => void loadAnalyzeHistory());
$("btn-analyze-copy-raw")?.addEventListener("click", (e) => {
  const text = $("analyze-raw")?.textContent || "";
  if (text) copyText(text, e.currentTarget);
});

$("btn-generate")?.addEventListener("click", onGenerate);

$("btn-download")?.addEventListener("click", () => {
  saveVideoFile(currentVideoUrl, currentVideoName);
});
$("btn-preview-zoom-in")?.addEventListener("click", () => {
  setPreviewZoom(previewZoom + PREVIEW_ZOOM_STEP);
});
$("btn-preview-zoom-out")?.addEventListener("click", () => {
  setPreviewZoom(previewZoom - PREVIEW_ZOOM_STEP);
});
$("btn-preview-zoom-reset")?.addEventListener("click", resetPreviewView);
$("btn-preview-expand")?.addEventListener("click", () => {
  previewExpanded = true;
  renderPreview();
});
$("btn-preview-shrink")?.addEventListener("click", resetPreviewView);

$("btn-settings-refresh-all")?.addEventListener("click", (e) => {
  refreshSettingsSection("all", e.currentTarget);
});
$("btn-setup-refresh")?.addEventListener("click", () => void loadSetupPanel());
$("btn-setup-run")?.addEventListener("click", (e) => void runSetupWizard(e.currentTarget));
$("btn-backup-create")?.addEventListener("click", (e) => {
  createDataBackup(e.currentTarget).catch((err) =>
    showToast(err.message || "Yedekleme basarisiz", 5000)
  );
});
$("btn-backup-open-folder")?.addEventListener("click", () => void openBackupFolder());
$("btn-live-system-refresh")?.addEventListener("click", (e) => {
  const btn = e.currentTarget;
  const prev = btn?.textContent;
  if (btn) btn.textContent = "Yenileniyor…";
  loadLiveSystemPanel()
    .catch(() => showToast("Canli sistem yenilenemedi", 4000))
    .finally(() => {
      if (btn && prev) btn.textContent = prev;
    });
});
$("btn-setup-modal-run")?.addEventListener("click", (e) => void runSetupWizard(e.currentTarget));
$("btn-setup-modal-later")?.addEventListener("click", () => {
  setupModalDismissed = true;
  stopSetupPolling();
  hideSetupModal();
});
$("btn-stock-api-save")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Kaydediliyor…", () => saveStockApiSettings()).catch((err) =>
    showToast(err.message || "Kayit basarisiz", 5000)
  );
});
$("btn-stock-api-test")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Test ediliyor…", () => testStockApiSettings()).catch((err) =>
    showToast(err.message || "Test basarisiz", 5000)
  );
});
$("btn-llm-api-save")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Kaydediliyor…", () => saveLlmApiSettings()).catch((err) =>
    showToast(err.message || "Kayit basarisiz", 5000)
  );
});
$("btn-llm-api-test")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Test ediliyor…", () => testLlmApiSettings()).catch((err) =>
    showToast(err.message || "Test basarisiz", 5000)
  );
});
$("llm-api-provider")?.addEventListener("change", () => syncLlmApiProviderUi());
["openai", "nvidia", "gemini", "grok", "claude"].forEach((p) => {
  $(`llm-api-${p}-key`)?.addEventListener("change", () => {
    if (($("llm-api-provider")?.value || "") === p) void refreshLlmApiModels(p);
  });
});
$("btn-minimax-h3-save")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Kaydediliyor…", () => saveMinimaxH3Settings()).catch((err) =>
    showToast(err.message || "Kayit basarisiz", 5000)
  );
});
$("btn-minimax-h3-test")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Test ediliyor…", () => testMinimaxH3Settings()).catch((err) =>
    showToast(err.message || "Test basarisiz", 5000)
  );
});
$("btn-minimax-h3-start")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Baslatiliyor…", () => startMinimaxH3Studio()).catch((err) =>
    showToast(err.message || "Baslatilamadi", 6000)
  );
});
$("btn-telegram-save")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Kaydediliyor…", () =>
    saveTelegramSettings()
  ).catch((err) => showToast(err.message || "Kayit basarisiz", 5000));
});
$("btn-telegram-discover")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Araniyor…", () =>
    discoverTelegramChat()
  ).catch((err) => showToast(err.message || "Chat ID bulunamadi", 6000));
});
$("btn-telegram-test")?.addEventListener("click", (e) => {
  runSettingsButton(e.currentTarget, "Gonderiliyor…", () =>
    testTelegramNotification()
  ).catch((err) => showToast(err.message || "Test basarisiz", 6000));
});
$("btn-hooks-compose-open")?.addEventListener("click", () => openHooksCompose());
$("btn-hooks-cancel")?.addEventListener("click", () => closeHooksCompose(true));
$("btn-hooks-save")?.addEventListener("click", () => void saveHookExample());
$("hooks-new-text")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    void saveHookExample();
  }
  if (e.key === "Escape") {
    e.preventDefault();
    closeHooksCompose(true);
  }
});
$("hooks-niche-select")?.addEventListener("change", () => {
  closeHooksCompose(true);
  void loadHooksSettings();
});
document.querySelectorAll("[data-refresh-section]").forEach((btn) => {
  btn.addEventListener("click", () =>
    refreshSettingsSection(btn.dataset.refreshSection, btn)
  );
});
document.querySelectorAll("[data-open-folder]").forEach((btn) => {
  btn.addEventListener("click", () => openSettingsFolder(btn.dataset.openFolder));
});
{
  const pickerFor = { rvc: "upload-rvc-file", bgm: "upload-bgm-file", intro: "upload-channel-file", outro: "upload-channel-file" };
  let pendingUpload = null;
  document.querySelectorAll("[data-upload-pick]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = $(pickerFor[btn.dataset.uploadPick]);
      if (!input) return;
      pendingUpload = { kind: btn.dataset.uploadPick, btn };
      input.value = "";
      input.click();
    });
  });
  new Set(Object.values(pickerFor)).forEach((id) => {
    $(id)?.addEventListener("change", (e) => {
      if (!pendingUpload) return;
      const { kind, btn } = pendingUpload;
      pendingUpload = null;
      void uploadSettingsFiles(kind, e.target.files, btn);
    });
  });
  $("settings-panel-files")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-delete-asset]");
    if (btn) void deleteSettingsAsset(btn.dataset.deleteAsset, btn.dataset.id, btn.dataset.label || btn.dataset.id);
  });
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && previewExpanded) {
    resetPreviewView();
  }
  if (e.key === "Escape" && !$("gallery-detail-modal")?.classList.contains("hidden")) {
    closeGalleryDetailModal();
  }
});

if (typeof Notification !== "undefined" && Notification.permission === "default") {
  Notification.requestPermission().catch(() => {});
}

window.addEventListener("unhandledrejection", (ev) => {
  const msg = ev.reason?.message || String(ev.reason || "");
  if (/is not valid JSON|Unexpected token/i.test(msg)) {
    ev.preventDefault();
    setStatus(
      "Sunucu beklenmeyen yanit verdi (motor/Ollama). Uygulamayi yeniden baslatin; ollama serve acik mi kontrol edin.",
      true
    );
  }
});

window.addEventListener("beforeunload", () => releaseLlmResources());
window.addEventListener("pagehide", () => releaseLlmResources());


initCustomSelects();
initFieldHelp();
switchProduceSubTab(
  PRODUCE_SUBTABS.includes(localStorage.getItem(PRODUCE_SUBTAB_KEY))
    ? localStorage.getItem(PRODUCE_SUBTAB_KEY)
    : "short"
);
renderLongformChapters();
void showLatestOutput({ autoplay: false });

$("btn-longform-plan")?.addEventListener("click", () => onLongformPlan());
$("btn-longform-think-open")?.addEventListener("click", () => onLongformThink());
$("btn-longform-think-again")?.addEventListener("click", () => onLongformThink());
$("btn-longform-think-plan")?.addEventListener("click", () => onLongformThinkPlan());
$("btn-longform-think-close")?.addEventListener("click", () => {
  $("longform-think-panel")?.classList.add("hidden");
});
$("btn-longform-add-chapter")?.addEventListener("click", () => {
  if (longformChapters.length >= 12) {
    showToast("En fazla 12 bolum");
    return;
  }
  longformChapters.push({ title: `Bolum ${longformChapters.length + 1}`, script: "" });
  renderLongformChapters();
});
$("btn-longform-generate")?.addEventListener("click", () => onLongformGenerate());
$("btn-longform-retry")?.addEventListener("click", () => onLongformRetry());
$("btn-longform-drafts-refresh")?.addEventListener("click", () => loadLongformDrafts());
document.querySelectorAll(".btn-stop-production").forEach((btn) => {
  btn.addEventListener("click", () => stopProduction());
});
$("btn-longform-open-gallery")?.addEventListener("click", () => {
  setGalleryViewMode("long");
  switchTab("gallery");
});
$("longform-dual-language")?.addEventListener("change", () => {
  $("longform-dual-hint")?.classList.toggle("hidden", !$("longform-dual-language")?.checked);
  updateLongformPlanSummary();
});
$("longform-platform")?.addEventListener("change", () => {
  syncLongformAspectFromPlatform();
});
$("longform-aspect")?.addEventListener("change", () => {
  updateLongformAspectHint();
});
updateLongformAspectHint();
$("longform-subject")?.addEventListener("input", () => {
  updateLongformPlanSummary();
  renderLongformChapters();
});

updatePill();
updateOllamaPill();
migrateVoicePrefsToMale();
migrateEditorPrefer9b();
migrateVoiceRvcPipeline();
applyConfigDefaults();
pollHealthStartup();
loadConfig().then(() => {
  loadHistory();
  loadDrafts();
  loadLongformDrafts();
  updateDualLanguageUi();
  void loadTopicMemoryHint();
  void loadProducedTopics();
  void checkRestoredQueue();
  void prefetchGalleryPublishBackfill();
  void maybeShowSetupModal();
});
setInterval(refreshMotorStatus, 12000);
setInterval(refreshOllamaStatus, 15000);

const SHORT_PRODUCTION_MODE_KEY = "aki_short_production_mode";

function syncShortProductionMode() {
  const manual = !!$("production-mode-manual")?.checked;
  const source = $("source");
  document.querySelector(".ios-mode-switch")?.classList.toggle("is-manual", manual);
  const modeToggle = $("production-mode-toggle");
  if (modeToggle) modeToggle.setAttribute("aria-checked", manual ? "true" : "false");
  document.querySelectorAll("#source option[data-manual-only]").forEach((opt) => {
    opt.hidden = !manual;
    opt.disabled = !manual;
  });
  if (!manual && source?.selectedOptions?.[0]?.dataset?.manualOnly !== undefined) {
    source.value = "pexels";
  }
  const hint = $("short-mode-hint");
  if (hint) {
    hint.textContent = manual
      ? "Ses, muzik, altyazi, klipler ve AI promptlari detay sayfasinda ayri sunulur."
      : "Stok gorsellerle tam otomatik video uretimi.";
  }
  const generateBtn = $("btn-generate");
  if (generateBtn) {
    generateBtn.textContent = manual ? "Dosyalari uret" : "Videoyu uret";
    generateBtn.dataset.help = manual
      ? "Senaryo, ses, muzik, altyazi, klipler ve AI promptlarini ayri montaj dosyalari olarak hazirlar."
      : "Tum adimlari baslatir: senaryo, ses, stok klip, altyazi ve montaj.";
  }
  localStorage.setItem(SHORT_PRODUCTION_MODE_KEY, manual ? "manual" : "automatic");
  refreshAllCustomSelects?.();
}

if ($("production-mode-manual")) {
  $("production-mode-manual").checked =
    localStorage.getItem(SHORT_PRODUCTION_MODE_KEY) === "manual";
  $("production-mode-manual").addEventListener("change", syncShortProductionMode);
}
$("production-mode-toggle")?.addEventListener("click", () => {
  const input = $("production-mode-manual");
  if (!input) return;
  input.checked = !input.checked;
  syncShortProductionMode();
});
document.querySelectorAll("[data-production-mode]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = $("production-mode-manual");
    if (!input) return;
    input.checked = btn.dataset.productionMode === "manual";
    syncShortProductionMode();
  });
});
syncShortProductionMode();

/* ——— AI gorsel / video (Fooocus + WanGP elle) ——— */
const AI_VISUAL_KEY = "aki_ai_manual_visuals";
let aiVisualSelected = new Set();
let aiVisualAwaiting = null; // { batchId, taskIndex }

function syncAiVisualPanel() {
  const pinokio = ($("source")?.value || "") === "pinokio";
  if (pinokio) {
    if ($("ai-manual-visuals")) $("ai-manual-visuals").checked = true;
    if ($("ai-visual-auto-minimax")) $("ai-visual-auto-minimax").checked = true;
    if ($("ai-visual-continue")) $("ai-visual-continue").checked = true;
  }
  const on = pinokio || !!$("ai-manual-visuals")?.checked;
  const panel = $("ai-visual-panel");
  if (panel) {
    panel.classList.toggle("hidden", !on);
    panel.hidden = !on;
  }
  // Kaynak secilebilir kalsin — Pinokio artik dropdown'da
  const source = $("source");
  if (source) source.disabled = false;
  localStorage.setItem(AI_VISUAL_KEY, !pinokio && on ? "1" : "0");
  if (on) void loadAiVisualAssets();
  syncAiVisualResumeBtn();
}

function selectedAiVisualIds() {
  return Array.from(aiVisualSelected);
}

function setAiVisualPromptStatus(msg, isErr) {
  const el = $("ai-visual-prompt-status");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.toggle("error", !!isErr);
}

function applyAiVisualPromptPack(pack) {
  if (!pack) return;
  if ($("ai-visual-wan-out")) $("ai-visual-wan-out").value = pack.wan?.prompt_block || "";
  if ($("ai-visual-fooocus-out")) $("ai-visual-fooocus-out").value = pack.fooocus?.prompt || "";
  if ($("ai-visual-fooocus-neg"))
    $("ai-visual-fooocus-neg").value = pack.fooocus?.negative_prompt || "";
  $("btn-ai-visual-copy-wan")?.removeAttribute("disabled");
  $("btn-ai-visual-copy-fooocus")?.removeAttribute("disabled");
  if (pack.segment_count && $("ai-visual-segments")) {
    $("ai-visual-segments").value = String(pack.segment_count);
  }
}

function syncAiVisualResumeBtn() {
  const btn = $("btn-ai-visual-resume");
  if (!btn) return;
  const waiting = !!aiVisualAwaiting;
  btn.hidden = !waiting;
  btn.disabled = !waiting || selectedAiVisualIds().length < 1;
}

function syncAiVisualAwaiting(data) {
  if (!$("ai-manual-visuals")?.checked) {
    aiVisualAwaiting = null;
    syncAiVisualResumeBtn();
    return;
  }
  const tasks = data?.tasks || [];
  const idx = tasks.findIndex(
    (t) => t.state === 4 && t.phase === "awaiting_ai_visuals"
  );
  if (idx < 0) {
    if (aiVisualAwaiting && data?.batch_id === aiVisualAwaiting.batchId) {
      aiVisualAwaiting = null;
      setAiVisualPromptStatus("Montaj devam ediyor…");
    }
    syncAiVisualResumeBtn();
    return;
  }
  const t = tasks[idx];
  const batchId = data.batch_id || currentBatchId;
  aiVisualAwaiting = {
    batchId,
    taskIndex: t.ai_task_index != null ? t.ai_task_index : idx,
  };
  if ($("ai-manual-visuals") && !$("ai-manual-visuals").checked) {
    $("ai-manual-visuals").checked = true;
    syncAiVisualPanel();
  } else {
    const panel = $("ai-visual-panel");
    if (panel) {
      panel.classList.remove("hidden");
      panel.hidden = false;
    }
  }
  if (t.ai_prompts_status === "generating") {
    setAiVisualPromptStatus("Senaryo hazir — H3 Studio + Qwen promptlari uretiliyor…");
  } else if (t.ai_prompts_status === "minimax_running") {
    if (t.ai_prompts) applyAiVisualPromptPack(t.ai_prompts);
    const mp = t.minimax_progress;
    const frac = mp?.total ? ` (${mp.done || 0}/${mp.total})` : "";
    setAiVisualPromptStatus(
      `H3 Studio otomatik uretiyor${frac}… ${t.minimax_status_text || "bekleyin"}`
    );
  } else if (t.ai_prompts_status === "error") {
    setAiVisualPromptStatus(
      t.ai_prompts_error || "Prompt hatasi — yine de dosya yukleyip devam edebilirsin.",
      true
    );
  } else if (t.ai_prompts) {
    applyAiVisualPromptPack(t.ai_prompts);
    const n = t.ai_prompts.segment_count || 0;
    const total = t.ai_prompts.total_seconds || n * 5;
    if (t.minimax_status === "error") {
      setAiVisualPromptStatus(
        `H3 Studio otomatik basarisiz: ${t.minimax_error || "hata"}. Elle uretip dosya sec.`,
        true
      );
    } else {
      setAiVisualPromptStatus(
        `Senaryoya gore ${n}×5 sn prompt hazir (≈${total} sn). Otomatik kapaliysa Pinokio'da uret → Montaja devam.`
      );
    }
  } else {
    setAiVisualPromptStatus("AI gorsel bekleniyor — dosya yukle ve Montaja devam.");
  }
  void loadAiVisualAssets();
  syncAiVisualResumeBtn();
}

function renderAiVisualAssets(assets) {
  const list = $("ai-visual-assets");
  if (!list) return;
  if (!assets?.length) {
    list.innerHTML = '<li class="history-empty">Henuz dosya yok.</li>';
    syncAiVisualResumeBtn();
    return;
  }
  const valid = new Set(assets.map((a) => a.id));
  aiVisualSelected = new Set([...aiVisualSelected].filter((id) => valid.has(id)));
  list.innerHTML = assets
    .map((a) => {
      const checked = aiVisualSelected.has(a.id) ? "checked" : "";
      const thumb =
        a.kind === "image"
          ? `<img class="ai-visual-thumb" src="${escapeHtml(a.url)}" alt="" />`
          : `<video class="ai-visual-thumb" src="${escapeHtml(a.url)}" muted></video>`;
      return `<li class="ai-visual-asset-item" data-id="${escapeHtml(a.id)}">
        <label class="ai-visual-asset-label">
          <input type="checkbox" class="ai-visual-asset-check" data-id="${escapeHtml(a.id)}" ${checked} />
          ${thumb}
          <span class="ai-visual-asset-meta">
            <strong>${escapeHtml(a.name)}</strong>
            <span class="history-meta">${a.kind} · ${Math.round((a.size || 0) / 1024)} KB</span>
          </span>
        </label>
        <button type="button" class="btn-ghost btn-sm ai-visual-del" data-id="${escapeHtml(a.id)}">Sil</button>
      </li>`;
    })
    .join("");
  list.querySelectorAll(".ai-visual-asset-check").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = cb.dataset.id;
      if (cb.checked) aiVisualSelected.add(id);
      else aiVisualSelected.delete(id);
      syncAiVisualResumeBtn();
    });
  });
  list.querySelectorAll(".ai-visual-del").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.id;
      try {
        const r = await fetch(`/api/ai-visuals/assets/${encodeURIComponent(id)}`, {
          method: "DELETE",
        });
        const data = await readApiJson(r);
        if (!r.ok) throw apiError(data, "Silinemedi");
        aiVisualSelected.delete(id);
        renderAiVisualAssets(data.assets || []);
      } catch (e) {
        setAiVisualPromptStatus(e?.message || "Silinemedi", true);
      }
    });
  });
  syncAiVisualResumeBtn();
}

async function loadAiVisualAssets() {
  try {
    const r = await fetch("/api/ai-visuals/assets");
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Liste alinamadi");
    renderAiVisualAssets(data.assets || []);
  } catch (e) {
    setAiVisualPromptStatus(e?.message || "Liste alinamadi", true);
  }
}

async function uploadAiVisualFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const fd = new FormData();
  files.forEach((f) => fd.append("files", f));
  setAiVisualPromptStatus(`${files.length} dosya yukleniyor…`);
  try {
    const r = await fetch("/api/ai-visuals/upload", { method: "POST", body: fd });
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Yukleme basarisiz");
    (data.assets || []).forEach((a) => aiVisualSelected.add(a.id));
    renderAiVisualAssets(data.all || data.assets || []);
    setAiVisualPromptStatus(
      aiVisualAwaiting
        ? `${files.length} dosya eklendi — sec, Montaja devam.`
        : `${files.length} dosya eklendi.`
    );
  } catch (e) {
    setAiVisualPromptStatus(e?.message || "Yukleme hatasi", true);
  }
}

$("ai-manual-visuals")?.addEventListener("change", syncAiVisualPanel);
$("source")?.addEventListener("change", () => {
  syncShortProductionMode();
  syncAiVisualPanel();
  refreshAllCustomSelects?.();
});
if (localStorage.getItem(AI_VISUAL_KEY) === "1" && $("ai-manual-visuals")) {
  $("ai-manual-visuals").checked = true;
}
syncAiVisualPanel();

$("btn-ai-visual-resume")?.addEventListener("click", async () => {
  if (!aiVisualAwaiting?.batchId) {
    setAiVisualPromptStatus("Bekleyen AI gorsel adimi yok — once Videoyu uret.", true);
    return;
  }
  const ids = selectedAiVisualIds();
  if (!ids.length) {
    setAiVisualPromptStatus("En az bir gorsel/video sec.", true);
    return;
  }
  const btn = $("btn-ai-visual-resume");
  if (btn) btn.disabled = true;
  setAiVisualPromptStatus("Montaja devam ediliyor…");
  try {
    const r = await fetch(
      `/api/batch/${encodeURIComponent(aiVisualAwaiting.batchId)}/ai-visuals/resume`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_ids: ids,
          task_index: aiVisualAwaiting.taskIndex,
        }),
      }
    );
    const data = await readApiJson(r);
    if (!r.ok) throw apiError(data, "Devam edilemedi");
    setAiVisualPromptStatus("Dosyalar alindi — TTS / montaj suruyor…");
    aiVisualAwaiting = null;
    syncAiVisualResumeBtn();
  } catch (e) {
    setAiVisualPromptStatus(e?.message || "Devam hatasi", true);
    syncAiVisualResumeBtn();
  }
});

$("btn-ai-visual-copy-wan")?.addEventListener("click", (e) => {
  copyText(($("ai-visual-wan-out")?.value || "").trim(), e.currentTarget);
});
$("btn-ai-visual-copy-fooocus")?.addEventListener("click", (e) => {
  const p = ($("ai-visual-fooocus-out")?.value || "").trim();
  const n = ($("ai-visual-fooocus-neg")?.value || "").trim();
  copyText(n ? `${p}\n\nNegative:\n${n}` : p, e.currentTarget);
});

$("btn-ai-visual-pick")?.addEventListener("click", () => $("ai-visual-file")?.click());
$("ai-visual-file")?.addEventListener("change", (e) => {
  void uploadAiVisualFiles(e.target.files);
  e.target.value = "";
});

const drop = $("ai-visual-drop");
if (drop) {
  ["dragenter", "dragover"].forEach((ev) => {
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((ev) => {
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.remove("dragover");
    });
  });
  drop.addEventListener("drop", (e) => {
    void uploadAiVisualFiles(e.dataTransfer?.files);
  });
}

$("btn-ai-visual-refresh")?.addEventListener("click", () => void loadAiVisualAssets());
$("btn-ai-visual-select-all")?.addEventListener("click", () => {
  document.querySelectorAll(".ai-visual-asset-check").forEach((cb) => {
    cb.checked = true;
    aiVisualSelected.add(cb.dataset.id);
  });
  syncAiVisualResumeBtn();
});
$("btn-ai-visual-clear-sel")?.addEventListener("click", () => {
  aiVisualSelected.clear();
  document.querySelectorAll(".ai-visual-asset-check").forEach((cb) => {
    cb.checked = false;
  });
  syncAiVisualResumeBtn();
});
