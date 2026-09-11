/* ══════════════════════════════════════════════════════════════════════════
   SaintessEngine 工作室 —— 主题系统（预设 + 自定义）

   设计   token 由本模块在运行时写入 <html style="--bg-0:…">；
          app.css 里的 :root 只是「无 JS 兜底」（深色 · 猫猫夜）。
   加载   必须在 <head> 同步加载（在首屏绘制前把配色写进去，否则会闪一下默认色）。
   用法   SETheme.apply()                  应用当前设置
          SETheme.get() / set({...})        读写设置（自动落盘 + 应用）
          SETheme.tokens()                  当前生效的完整 token 表（自定义编辑用）
          SETheme.PRESETS / ACCENT_CHOICES  给 UI 渲染用
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ── 颜色工具 ── */
  function hex2rgb(h) {
    h = String(h || '').replace('#', '');
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function rgb2hex(r, g, b) {
    return '#' + [r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
  }
  function rgba(hex, a) { const [r, g, b] = hex2rgb(hex); return `rgba(${r},${g},${b},${a})`; }
  function mix(a, b, t) {
    const A = hex2rgb(a), B = hex2rgb(b);
    return rgb2hex(A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t);
  }
  function lum(hex) {
    const c = hex2rgb(hex).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  /* 在这个底色上该用深字还是白字（用于主按钮 / 错误角标） */
  function readableOn(hex) { return lum(hex) > 0.42 ? '#1e1e2e' : '#ffffff'; }

  /* `#rgb` / `#rrggbb` → 规范化；非颜色返回 null */
  function normHex(v) {
    if (typeof v !== 'string') return null;
    const m = v.trim().match(/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/);
    if (!m) return null;
    let h = m[1];
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    return '#' + h.toLowerCase();
  }

  /* ── 模式基线（两套）── */
  const MODE_BASE = {
    dark: {
      bg0: '#11111b', bg1: '#181825', bg2: '#1e1e2e', bg3: '#313244', bg4: '#45475a',
      line: '#2c2c3e', line2: '#45475a',
      fg0: '#cdd6f4', fg1: '#bac2de', fg2: '#a6adc8', fg3: '#7f849c',
      accent: '#cba6f7', ok: '#a6e3a1', warn: '#f9e2af', err: '#f38ba8',
      kPhys: '#bac2de', kMagi: '#89b4fa', kHeal: '#a6e3a1', kBuff: '#f9e2af',
      kPassive: '#cba6f7', kSummon: '#94e2d5', kTrue: '#f38ba8', kTaunt: '#f5c2e7',
      diffDel: '#f0a3b3', diffAdd: '#a6e3a1', brand2: '#89b4fa',
      sh1: '0 1px 2px rgba(0,0,0,.4)', sh2: '0 8px 24px rgba(0,0,0,.45)',
      sh3: '0 20px 60px rgba(0,0,0,.62)', scrim: 'rgba(11,11,20,.58)',
    },
    light: {
      bg0: '#e6e9ef', bg1: '#eff1f5', bg2: '#f7f8fa', bg3: '#ffffff', bg4: '#e2e5ec',
      line: '#d5d9e2', line2: '#bcc0cc',
      fg0: '#4c4f69', fg1: '#5c5f77', fg2: '#7c7f93', fg3: '#9ca0b0',
      accent: '#8839ef', ok: '#40a02b', warn: '#df8e1d', err: '#d20f39',
      kPhys: '#5c5f77', kMagi: '#1e66f5', kHeal: '#40a02b', kBuff: '#df8e1d',
      kPassive: '#8839ef', kSummon: '#179299', kTrue: '#d20f39', kTaunt: '#ea76cb',
      diffDel: '#c62b48', diffAdd: '#2f8a1f', brand2: '#1e66f5',
      sh1: '0 1px 2px rgba(76,79,105,.12)', sh2: '0 8px 24px rgba(76,79,105,.14)',
      sh3: '0 20px 60px rgba(76,79,105,.2)', scrim: 'rgba(76,79,105,.32)',
    },
  };

  /* 自定义编辑器里可调的字段（顺序 = 界面顺序） */
  const EDITABLE = [
    { k: 'bg0', label: '应用底' }, { k: 'bg1', label: '面板' },
    { k: 'bg2', label: '抬升（顶栏）' }, { k: 'bg3', label: '控件' }, { k: 'bg4', label: '悬停' },
    { k: 'line', label: '边框' }, { k: 'line2', label: '边框·强' },
    { k: 'fg0', label: '文字·主' }, { k: 'fg1', label: '文字·次' }, { k: 'fg2', label: '文字·弱' },
    { k: 'accent', label: '强调色' },
    { k: 'ok', label: '成功' }, { k: 'warn', label: '警告' }, { k: 'err', label: '错误' },
  ];

  /* ── 预设主题 ── */
  const PRESETS = [
    { id: 'mocha', name: '猫猫夜', mode: 'dark', tags: '低饱和 柔紫', tokens: {} },
    {
      id: 'midnight', name: '极夜', mode: 'dark', tags: '冷蓝 深空',
      tokens: {
        bg0: '#16161e', bg1: '#1a1b26', bg2: '#1f2335', bg3: '#292e42', bg4: '#3b4261',
        line: '#2a2f45', line2: '#3b4261',
        fg0: '#c0caf5', fg1: '#a9b1d6', fg2: '#787c99', fg3: '#565f89',
        accent: '#7aa2f7', ok: '#9ece6a', warn: '#e0af68', err: '#f7768e',
        kPhys: '#a9b1d6', kMagi: '#7aa2f7', kHeal: '#9ece6a', kBuff: '#e0af68',
        kPassive: '#bb9af7', kSummon: '#7dcfff', kTrue: '#f7768e', kTaunt: '#ff9ec7',
        brand2: '#7aa2f7',
      },
    },
    {
      id: 'forest', name: '幽林', mode: 'dark', tags: '墨绿 沉静',
      tokens: {
        bg0: '#0d1310', bg1: '#121a16', bg2: '#17211c', bg3: '#22302a', bg4: '#2f4038',
        line: '#1f2b25', line2: '#33453c',
        fg0: '#d6e3da', fg1: '#b6c7bc', fg2: '#8ea396', fg3: '#6b7f72',
        accent: '#86d3a4', ok: '#86d3a4', warn: '#ddc07a', err: '#e08c8c',
        kPhys: '#b6c7bc', kMagi: '#7fb5d6', kHeal: '#86d3a4', kBuff: '#ddc07a',
        kPassive: '#b6a2e0', kSummon: '#79cdc0', kTrue: '#e08c8c', kTaunt: '#d9a3c4',
        brand2: '#79cdc0',
      },
    },
    {
      id: 'dusk', name: '暮色', mode: 'dark', tags: '暖褐 琥珀',
      tokens: {
        bg0: '#15100d', bg1: '#1b1512', bg2: '#221b17', bg3: '#2e2521', bg4: '#3d322c',
        line: '#2a211d', line2: '#3d322c',
        fg0: '#eee0d5', fg1: '#d3c1b4', fg2: '#a8988c', fg3: '#82736a',
        accent: '#e8a87c', ok: '#a8c98a', warn: '#e0c07a', err: '#e08a7a',
        kPhys: '#d3c1b4', kMagi: '#8fb8d8', kHeal: '#a8c98a', kBuff: '#e0c07a',
        kPassive: '#c0a0d8', kSummon: '#7fc8bd', kTrue: '#e08a7a', kTaunt: '#dda0b8',
        brand2: '#e8a87c',
      },
    },
    { id: 'latte', name: '白昼', mode: 'light', tags: '冷白 柔紫', tokens: {} },
    {
      id: 'paper', name: '纸白', mode: 'light', tags: '暖白 赭石',
      tokens: {
        bg0: '#ece5da', bg1: '#f6f1e8', bg2: '#fdfaf4', bg3: '#ffffff', bg4: '#e6ded1',
        line: '#ddd4c6', line2: '#c8bdab',
        fg0: '#4a4038', fg1: '#5e5349', fg2: '#7d7166', fg3: '#9b9084',
        accent: '#b0641f', ok: '#4f8a3a', warn: '#c08a1e', err: '#c0392b',
        kPhys: '#5e5349', kMagi: '#2361a8', kHeal: '#4f8a3a', kBuff: '#c08a1e',
        kPassive: '#8250c0', kSummon: '#1a8a8a', kTrue: '#c0392b', kTaunt: '#b0559a',
        brand2: '#b0641f',
      },
    },
    {
      id: 'solar', name: '晴日', mode: 'light', tags: '米黄 靛蓝',
      tokens: {
        bg0: '#eee8d5', bg1: '#f7f1e3', bg2: '#fdf6e3', bg3: '#fffcf5', bg4: '#e4dcc6',
        line: '#ded8c4', line2: '#c9c2aa',
        fg0: '#586e75', fg1: '#657b83', fg2: '#839496', fg3: '#93a1a1',
        accent: '#268bd2', ok: '#859900', warn: '#b58900', err: '#dc322f',
        kPhys: '#657b83', kMagi: '#268bd2', kHeal: '#859900', kBuff: '#b58900',
        kPassive: '#6c71c4', kSummon: '#2aa198', kTrue: '#dc322f', kTaunt: '#d33682',
        brand2: '#268bd2',
      },
    },
  ];

  /* ── 强调色快选（按模式取不同明度，保证对比度）── */
  const ACCENT_CHOICES = {
    violet: { name: '紫罗兰', dark: '#cba6f7', light: '#8839ef' },
    ocean:  { name: '海蓝',   dark: '#89b4fa', light: '#1e66f5' },
    amber:  { name: '琥珀',   dark: '#f9e2af', light: '#c47a12' },
    jade:   { name: '青碧',   dark: '#94e2d5', light: '#179299' },
    rose:   { name: '蔷薇',   dark: '#f5c2e7', light: '#d20f9c' },
    slate:  { name: '石墨',   dark: '#b8bfd0', light: '#4c4f69' },
  };

  /* ── 读写设置 ── */
  const LS = {
    follow: 'fe.follow',            // '1' = 跟随系统
    mode: 'fe.mode',                // 'dark' | 'light'
    presetDark: 'fe.preset.dark',   // 预设 id 或 'custom'
    presetLight: 'fe.preset.light',
    accent: 'fe.accent',            // 快选 key 或 'custom'
    accentHex: 'fe.accent.hex',     // 自定义强调色
    custom: 'fe.custom',            // {"dark":{tokens},"light":{tokens}}
    wall: 'fe.wall',                // 壁纸：data URL 或远程 URL（空 = 无）
    wallPreset: 'fe.wall.preset',   // 内置渐变壁纸 id
    wallOp: 'fe.wall.op', wallBlur: 'fe.wall.blur',
    wallSat: 'fe.wall.sat', wallDim: 'fe.wall.dim',
  };
  const get = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const set = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* 隐私模式 */ } };

  const sysLight = () => !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches);

  function state() {
    const follow = get(LS.follow, '0') === '1';
    const mode = follow ? (sysLight() ? 'light' : 'dark') : (get(LS.mode, 'dark') === 'light' ? 'light' : 'dark');
    const presetDark = get(LS.presetDark, 'mocha');
    const presetLight = get(LS.presetLight, 'latte');
    const accent = get(LS.accent, 'preset');   // 'preset' = 用预设自带签名色
    return {
      follow,
      modePref: get(LS.mode, 'dark'),
      mode,                                   // 已解析（跟随系统后）
      presetDark, presetLight,
      presetId: mode === 'light' ? presetLight : presetDark,
      accent,
      accentHex: get(LS.accentHex, ''),
      custom: readCustom(),
    };
  }

  function readCustom() {
    try { const o = JSON.parse(get(LS.custom, '{}')); return o && typeof o === 'object' ? o : {}; }
    catch (e) { return {}; }
  }
  function writeCustom(o) { set(LS.custom, JSON.stringify(o)); }

  /* ── 生效 token 表 ── */
  function tokens() {
    const st = state();
    const t = Object.assign({}, MODE_BASE[st.mode]);
    if (st.presetId !== 'custom') {
      const p = PRESETS.find((x) => x.id === st.presetId);
      if (p && p.mode === st.mode) Object.assign(t, p.tokens);
    } else {
      Object.assign(t, (st.custom[st.mode] || {}));
    }
    // 强调色：'preset' = 保留预设签名色；否则用快选 / 自定义覆盖
    if (st.accent === 'custom') {
      const h = normHex(st.accentHex);
      if (h) t.accent = h;
    } else if (st.accent !== 'preset' && ACCENT_CHOICES[st.accent]) {
      t.accent = ACCENT_CHOICES[st.accent][st.mode];
    }
    return t;
  }

  /* ── 写入 CSS 变量 ── */
  function varMap() {
    const st = state();
    const t = tokens();
    const dark = st.mode === 'dark';
    return {
      '--bg-0': t.bg0, '--bg-1': t.bg1, '--bg-2': t.bg2, '--bg-3': t.bg3, '--bg-4': t.bg4,
      '--line': t.line, '--line-2': t.line2,
      '--fg-0': t.fg0, '--fg-1': t.fg1, '--fg-2': t.fg2, '--fg-3': t.fg3,
      '--accent': t.accent,
      '--accent-hi': dark ? mix(t.accent, '#ffffff', 0.18) : mix(t.accent, '#000000', 0.14),
      '--accent-dim': rgba(t.accent, dark ? 0.16 : 0.12),
      '--accent-soft': rgba(t.accent, 0.36),
      '--on-accent': readableOn(t.accent),
      '--ok': t.ok, '--warn': t.warn, '--err': t.err,
      '--ok-dim': rgba(t.ok, dark ? 0.14 : 0.12),
      '--warn-dim': rgba(t.warn, dark ? 0.13 : 0.14),
      '--err-dim': rgba(t.err, dark ? 0.14 : 0.09),
      '--ok-soft': rgba(t.ok, 0.32), '--warn-soft': rgba(t.warn, 0.36), '--err-soft': rgba(t.err, 0.32),
      '--on-err': readableOn(t.err), '--on-ok': readableOn(t.ok),
      '--k-phys': t.kPhys, '--k-magi': t.kMagi, '--k-heal': t.kHeal, '--k-buff': t.kBuff,
      '--k-passive': t.kPassive, '--k-summon': t.kSummon, '--k-true': t.kTrue, '--k-taunt': t.kTaunt,
      '--diff-del': t.diffDel, '--diff-add': t.diffAdd,
      '--sh1': t.sh1, '--sh2': t.sh2, '--sh3': t.sh3, '--scrim': t.scrim,
      '--brand-2': t.brand2,
    };
  }


  /* ══════════ 壁纸 ══════════
     存 localStorage（data URL 或远程 URL）。体积守卫：data URL > 3.5MB 拒绝
     （localStorage 配额约 5MB，且与主题设置共用）。
     内置 4 条纯 CSS 渐变壁纸，用户不找图也能试。 */
  const WALL_MAX = 3.5 * 1024 * 1024;

  const WALL_PRESETS = [
    { id: 'none',  name: '无',     css: '' },
    { id: 'aurora', name: '极光',  css: 'radial-gradient(1200px 700px at 18% 8%,#2b3a67 0%,transparent 60%),radial-gradient(1000px 800px at 82% 92%,#3d2b5c 0%,transparent 55%),linear-gradient(160deg,#0b1020,#131a2b 60%,#0d1424)' },
    { id: 'dawn',   name: '晨雾',  css: 'radial-gradient(900px 600px at 25% 20%,rgba(255,190,150,.55),transparent 62%),radial-gradient(800px 700px at 80% 85%,rgba(150,190,255,.5),transparent 58%),linear-gradient(160deg,#2b2333,#3a2f3f 55%,#241f2e)' },
    { id: 'deep',   name: '深海',  css: 'radial-gradient(1000px 700px at 70% 15%,#0e3b4a 0%,transparent 62%),radial-gradient(900px 800px at 20% 90%,#123040 0%,transparent 58%),linear-gradient(150deg,#06121a,#0a1c26 60%,#05101a)' },
    { id: 'ember',  name: '余烬',  css: 'radial-gradient(900px 600px at 78% 82%,rgba(220,120,60,.42),transparent 60%),radial-gradient(800px 600px at 22% 18%,rgba(120,60,80,.4),transparent 58%),linear-gradient(150deg,#1a1210,#241a15 55%,#160f0d)' },
    { id: 'paper',  name: '素纸',  css: 'radial-gradient(1000px 700px at 30% 10%,rgba(255,255,255,.85),transparent 60%),linear-gradient(160deg,#e8e4dc,#f2eee6 55%,#ded9cf)' },
  ];

  /* 壁纸设置（函数式，避免「导出对象被当函数调用」的坑） */
  function wall() {
    return {
      src: get(LS.wall, ''),                       // '' = 无
      preset: get(LS.wallPreset, 'none'),
      op: Number(get(LS.wallOp, '1')),
      blur: Number(get(LS.wallBlur, '0')),
      sat: Number(get(LS.wallSat, '1')),
      dim: Number(get(LS.wallDim, '0.45')),
    };
  }

  const wallActive = () => { const w = wall(); return !!(w.src || w.preset !== 'none'); };

  /* 生成 --wall 的 CSS 值 */
  function wallImage() {
    const w = wall();
    if (w.src) return `url("${w.src.replace(/"/g, '\\"')}")`;
    const pr = WALL_PRESETS.find((x) => x.id === w.preset);
    return pr && pr.css ? pr.css : '';
  }

  function applyWall() {
    const root = document.documentElement;
    const img = wallImage();
    if (!img) { root.removeAttribute('data-wall'); root.style.removeProperty('--wall'); return; }
    const st = state();
    const dark = st.mode === 'dark';
    // 压暗层：深色主题压得更狠，浅色主题用白雾
    const d = wall().dim;
    const scrim = dark
      ? `linear-gradient(rgba(0,0,0,${d}),rgba(0,0,0,${Math.min(1, d + 0.12)}))`
      : `linear-gradient(rgba(255,255,255,${d}),rgba(255,255,255,${Math.min(1, d + 0.08)}))`;
    root.style.setProperty('--wall', img);
    const w = wall();
    root.style.setProperty('--wall-op', String(w.op));
    root.style.setProperty('--wall-blur', w.blur + 'px');
    root.style.setProperty('--wall-sat', String(w.sat));
    root.style.setProperty('--wall-scrim', scrim);
    root.setAttribute('data-wall', '1');
  }

  /* 来源设置（data URL / 远程 URL / 内置预设） */
  function setWall(o) {
    if (o.clear) {
      set(LS.wall, ''); set(LS.wallPreset, 'none');
    }
    if (o.preset !== undefined) { set(LS.wallPreset, o.preset); set(LS.wall, ''); }
    if (o.url) {
      const u = String(o.url).trim();
      if (u) { set(LS.wall, u); set(LS.wallPreset, 'none'); }
    }
    if (o.dataUrl) {
      const d = String(o.dataUrl);
      if (d.length > WALL_MAX) return { ok: false, reason: `图片过大（${(d.length / 1048576).toFixed(1)}MB，上限 ${(WALL_MAX / 1048576).toFixed(1)}MB）。换小一点，或用「网址」引用。` };
      set(LS.wall, d); set(LS.wallPreset, 'none');
    }
    if (o.op !== undefined) set(LS.wallOp, String(o.op));
    if (o.blur !== undefined) set(LS.wallBlur, String(o.blur));
    if (o.sat !== undefined) set(LS.wallSat, String(o.sat));
    if (o.dim !== undefined) set(LS.wallDim, String(o.dim));
    applyWall();
    return { ok: true };
  }

  /* 估算当前壁纸占用（给界面显示） */
  function wallSize() {
    const s = wall().src;
    if (!s) return 0;
    return s.startsWith('data:') ? s.length : 0;
  }

  let _themeTimer = null;

  /* animate=true 时挂 140ms 的颜色过渡（仅切换瞬间，不常驻） */
  function apply(animate) {
    const st = state();
    const root = document.documentElement;
    if (animate !== false) {
      root.classList.add('theming');
      clearTimeout(_themeTimer);
      _themeTimer = setTimeout(() => root.classList.remove('theming'), 200);
    }
    const map = varMap();
    Object.keys(map).forEach((k) => root.style.setProperty(k, map[k]));
    root.setAttribute('data-theme', st.mode);          // 仅作语义标记（配色已内联）
    root.style.colorScheme = st.mode;
    applyWall();
  }

  /* ── 对外设置入口 ── */
  function update(patch) {
    if (patch.follow !== undefined) set(LS.follow, patch.follow ? '1' : '0');
    if (patch.modePref !== undefined) set(LS.mode, patch.modePref === 'light' ? 'light' : 'dark');
    if (patch.presetId !== undefined) {
      const p = PRESETS.find((x) => x.id === patch.presetId);
      const resolvedMode = p ? p.mode : state().mode;
      set(resolvedMode === 'light' ? LS.presetLight : LS.presetDark, patch.presetId);
      if (!state().follow) set(LS.mode, resolvedMode);
      if (patch.presetId === 'custom') {
        // 自定义：以当前生效配色为种子落盘
        const cur = readCustom();
        cur[resolvedMode] = cur[resolvedMode] || tokens();
        writeCustom(cur);
      }
    }
    if (patch.accent !== undefined) set(LS.accent, patch.accent);
    if (patch.accentHex !== undefined) {
      const h = normHex(patch.accentHex);
      if (h) { set(LS.accentHex, h); set(LS.accent, 'custom'); }
    }
    if (patch.token) {
      // 单个自定义 token（自动切到「自定义」预设）
      const st = state();
      const cur = readCustom();
      const seed = cur[st.mode] || tokens();
      seed[patch.token.k] = patch.token.v;
      cur[st.mode] = seed;
      writeCustom(cur);
      set(st.mode === 'light' ? LS.presetLight : LS.presetDark, 'custom');
    }
    if (patch.resetCustom) {
      const cur = readCustom();
      delete cur[patch.mode || state().mode];
      writeCustom(cur);
    }
    if (patch.resetAll) {
      Object.values(LS).forEach((k) => { try { localStorage.removeItem(k); } catch (e) { /* noop */ } });
      applyWall();
    }
    apply();
    return state();
  }

  /* 后台标签页里 setTimeout 会被节流（过渡类可能摘不掉）→ 回到前台时兜底清理 */
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) document.documentElement.classList.remove('theming');
  });

  /* 系统主题变化（跟随模式下自动重画） */
  function watchSystem() {
    if (!window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const on = () => { if (get(LS.follow, '0') === '1') apply(); };
    mq.addEventListener ? mq.addEventListener('change', on) : mq.addListener(on);
  }

  window.SETheme = {
    MODE_BASE, PRESETS, ACCENT_CHOICES, EDITABLE, LS,
    WALL_PRESETS, WALL_MAX,
    state, tokens, varMap, apply, update, watchSystem,
    normHex, mix, readableOn, sysLight,
    wall, wallActive, wallImage, wallSize, setWall,
  };

  /* head 同步执行：首屏前定色，避免闪白（不动画） */
  apply(false);
  watchSystem();
})();
