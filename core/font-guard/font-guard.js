// Font-only adaptation of Site Locale Control / FuckClaude (MIT).
// Source: https://github.com/LinXiaoTao/FuckClaude
// Upstream commit: bb0015805a4a92a7ed9221693219a69315123aee
// Scope: page-realm font measurement only; workers and DOM/CSS measurement are not covered.
(() => {
  "use strict";
  const installed = Symbol.for("claude-switcher.font-guard.v1");
  if (globalThis[installed]) return;
  // src/generated/fonts.ts
  var HIDDEN_FONTS = [
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimSun",
    "NSimSun",
    "SimHei",
    "KaiTi",
    "FangSong",
    "DengXian",
    "PingFang SC",
    "Hiragino Sans GB",
    "STHeiti",
    "STSong",
    "Songti SC",
    "Source Han Sans CN",
    "Source Han Sans SC",
    "Noto Sans CJK SC",
    "Noto Serif CJK SC",
    "WenQuanYi Micro Hei",
    "WenQuanYi Zen Hei",
    "Microsoft JhengHei",
    "PMingLiU",
    "MingLiU",
    "DFKai-SB",
    "PingFang TC",
    "PingFang HK",
    "Source Han Sans TW",
    "Noto Sans CJK TC",
    "MiSans",
    "MIUI",
    "HarmonyOS Sans SC",
    "HarmonyOS Sans",
    "HONOR Sans",
    "OPPO Sans",
    "vivo Sans",
    "Alibaba PuHuiTi",
    "Alibaba Sans",
    "DingTalk JinBuTi",
    "Douyin Sans",
    "HYQiHei",
    "FZShuSong-Z01S",
    "FZKai-Z03S",
    "FZHei-B01S",
    "FZFangSong-Z02S"
  ];

  // src/patch/fonts.ts
  var SIZE = /^(?:xx-small|x-small|small|medium|large|x-large|xx-large|xxx-large|larger|smaller|(?:\d+(?:\.\d+)?(?:px|em|rem|pt|pc|ex|ch|vh|vw|vmin|vmax|%))(?:\/(?:normal|\d+(?:\.\d+)?(?:px|em|rem|%)?))?)$/i;
  function tokenizeFont(font) {
    const tokens = [];
    let cur = "";
    let quote = "";
    for (let i = 0; i < font.length; i += 1) {
      const ch = font[i] ?? "";
      if (quote) {
        cur += ch;
        if (ch === "\\" && i + 1 < font.length) {
          cur += font[i + 1];
          i += 1;
          continue;
        }
        if (ch === quote) quote = "";
        continue;
      }
      if (ch === '"' || ch === "'") {
        quote = ch;
        cur += ch;
        continue;
      }
      if (ch === " " || ch === "	" || ch === "\n") {
        if (cur) tokens.push(cur);
        cur = "";
        continue;
      }
      cur += ch;
    }
    if (cur) tokens.push(cur);
    return tokens;
  }
  function splitFamilies(src) {
    const out = [];
    let cur = "";
    let quote = "";
    for (let i = 0; i < src.length; i += 1) {
      const ch = src[i] ?? "";
      if (quote) {
        cur += ch;
        if (ch === "\\" && i + 1 < src.length) {
          cur += src[i + 1];
          i += 1;
          continue;
        }
        if (ch === quote) quote = "";
        continue;
      }
      if (ch === '"' || ch === "'") {
        quote = ch;
        cur += ch;
        continue;
      }
      if (ch === ",") {
        if (cur.trim()) out.push(cur.trim());
        cur = "";
        continue;
      }
      cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }
  function unquoteFamily(family) {
    const text = family.trim().replace(/\s+/g, " ");
    if (text.length >= 2 && (text.startsWith('"') && text.endsWith('"') || text.startsWith("'") && text.endsWith("'"))) {
      return text.slice(1, -1).replace(/\\(.)/g, "$1").trim();
    }
    return text;
  }
  function hiddenSet(hidden) {
    if (Array.isArray(hidden)) return new Set(hidden.map((name) => name.toLowerCase()));
    return hidden instanceof Set ? hidden : new Set(hidden);
  }
  function parseFontShorthand(font) {
    const tokens = tokenizeFont(font);
    let sizeIdx = -1;
    for (let i = 0; i < tokens.length; i += 1) {
      if (SIZE.test(tokens[i] || "")) {
        sizeIdx = i;
        break;
      }
    }
    if (sizeIdx < 0) return null;
    return {
      prefix: tokens.slice(0, sizeIdx + 1).join(" "),
      families: splitFamilies(tokens.slice(sizeIdx + 1).join(" "))
    };
  }
  function fontWithoutHidden(font, hidden) {
    const parsed = parseFontShorthand(font);
    if (!parsed) return null;
    const names = hiddenSet(hidden);
    let removed = false;
    const kept = [];
    for (const family of parsed.families) {
      if (names.has(unquoteFamily(family).toLowerCase())) removed = true;
      else kept.push(family);
    }
    if (!removed) return null;
    const families = kept.length ? kept.join(", ") : "sans-serif";
    return `${parsed.prefix} ${families}`;
  }
  function fontSpecHasHidden(font, hidden) {
    const names = hiddenSet(hidden);
    const parsed = parseFontShorthand(font);
    if (parsed) return parsed.families.some((family) => names.has(unquoteFamily(family).toLowerCase()));
    const lower = font.toLowerCase();
    for (const name of names) {
      if (lower.includes(`"${name}"`) || lower.includes(`'${name}'`)) return true;
    }
    return false;
  }
  function replaceMethod(proto, key, fn) {
    Object.defineProperty(proto, key, {
      value: fn,
      writable: true,
      configurable: true,
      enumerable: false
    });
  }
  function wrapMeasure(proto, hidden) {
    if (!proto || typeof proto.measureText !== "function") return;
    const orig = proto.measureText;
    replaceMethod(proto, "measureText", function(text) {
      let rewritten = false;
      let prev = "";
      try {
        const next = fontWithoutHidden(String(this.font ?? ""), hidden);
        if (next) {
          prev = String(this.font ?? "");
          this.font = next;
          rewritten = true;
        }
      } catch {
        rewritten = false;
      }
      try {
        return orig.call(this, text);
      } finally {
        if (rewritten) {
          try {
            this.font = prev;
          } catch {
          }
        }
      }
    });
  }
  var HIDDEN = new Set(HIDDEN_FONTS.map((name) => name.toLowerCase()));
  function installFonts(scope) {
    wrapMeasure(scope.CanvasRenderingContext2D?.prototype, HIDDEN);
    wrapMeasure(scope.OffscreenCanvasRenderingContext2D?.prototype, HIDDEN);
    const fonts = scope.FontFaceSet?.prototype;
    if (!fonts || typeof fonts.check !== "function") return;
    const orig = fonts.check;
    replaceMethod(fonts, "check", function(font, text) {
      try {
        if (fontSpecHasHidden(String(font), HIDDEN)) return false;
      } catch {
      }
      return orig.call(this, font, text);
    });
  }

  installFonts(globalThis);
  Object.defineProperty(globalThis, installed, {value: true});
})();
