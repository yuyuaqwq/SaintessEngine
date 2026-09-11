/* schema_form.js —— JSON Schema → 表单渲染器（原生 DOM，零依赖）
 *
 * 渲染规则（EDITOR_SPEC.md「表单渲染规则」）：
 *   string + enum            → <select>
 *   string                   → <input type=text>（可挂联想 datalist）
 *   number / integer         → <input type=number>（带 min/max/step）
 *   boolean                  → <checkbox>
 *   object（有 properties）   → 折叠分组（递归渲染）
 *   object（仅 additionalProperties schema）→ 键值行编辑器（键为 propertyNames.enum 时用 select）
 *   array（元素为标量）        → 可增删的行列表
 *   array（元素为 enum）       → 多选标签 chips（原先是 JSON 兜底）
 *   array/formula 等复杂项     → JSON 兜底编辑框
 *   const / anyOf            → 常量显示 / 联合输入框
 *   description / $comment   → 字段下方灰字帮助
 *
 * 用法：
 *   const handle = SchemaForm.render(rootSchema, rootValue, {onChange});
 *   // 控件直接写回 rootValue（同一对象引用），onChange 用于标脏
 *   SchemaForm.markErrors(container, [{path:'$.kind', message:'...'}]);
 *
 * 可选：分组渲染（**按语义把字段分块**，不传则与旧行为完全一致）
 *   SchemaForm.render(def, value, {
 *     groups: [{id:'cost', label:'消耗与节奏', icon:'⚡', fields:['mp','cd']}],
 *     groupKey: 'skills',                    // 折叠状态的命名前缀（一般传域 id）
 *     collapsed: (key) => bool,              // key = groupKey + '#' + g.id
 *     onToggleGroup: (key, collapsed) => {}, // 折叠状态由调用方记住（重渲染不丢）
 *   });
 *   未出现在任何组里的字段 → 归入「未分组」（**不丢字段**，漏了就看得见）。
 *
 * 可选：控件形态与联想（**数据驱动**，由调用方按字段语义给）
 *   SchemaForm.render(def, value, {
 *     widget:     (path, schema) => 'textarea'|'lines'|'chips'|'pct'|null,
 *     suggest:    (path, schema) => ['候选值', ...],      // 文本/数字 → datalist
 *     suggestKey: (path, schema) => ['候选键', ...],      // 对象 → 键的 datalist
 *   });
 *   也认 schema 自带的 `x-widget`。
 */
window.SchemaForm = (function () {
  'use strict';

  function elem(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null && text !== '') e.textContent = String(text);
    return e;
  }
  function getIn(root, path) {
    let cur = root;
    for (const k of path) {
      if (cur === null || typeof cur !== 'object') return undefined;
      cur = cur[k];
    }
    return cur;
  }
  function setIn(root, path, val) {
    let cur = root;
    for (let i = 0; i < path.length - 1; i++) {
      const k = path[i];
      if (cur[k] === null || typeof cur[k] !== 'object') cur[k] = (typeof path[i + 1] === 'number') ? [] : {};
      cur = cur[k];
    }
    cur[path[path.length - 1]] = val;
  }
  function delIn(root, path) {
    let cur = root;
    for (let i = 0; i < path.length - 1; i++) {
      if (cur[path[i]] === undefined) return;
      cur = cur[path[i]];
    }
    delete cur[path[path.length - 1]];
  }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

  /* 字段路径（丢掉数组下标，联想按「字段」而不是「第几个元素」算） */
  function fieldPath(path) {
    return (path || []).filter(function (p) { return typeof p !== 'number'; });
  }
  function widgetOf(schema, path, ctx) {
    if (schema && schema['x-widget']) return schema['x-widget'];
    if (ctx && ctx.widget) {
      try { return ctx.widget(fieldPath(path).join('.'), schema) || null; } catch (e) { return null; }
    }
    return null;
  }
  function suggestList(schema, path, ctx, keyMode) {
    const fn = keyMode ? (ctx && ctx.suggestKey) : (ctx && ctx.suggest);
    if (!fn) return [];
    try {
      const out = fn(fieldPath(path).join('.'), schema) || [];
      return Array.isArray(out) ? out : [];
    } catch (e) { return []; }
  }
  /* 给控件挂联想（datalist 复用：同一 id 的 datalist 只建一次） */
  function attachList(inp, values, uid) {
    const vals = (values || []).filter(function (v) { return v !== undefined && v !== null && v !== ''; });
    if (!vals.length) return inp;
    const id = 'dl-' + uid;
    let dl = document.getElementById(id);
    if (!dl) {
      dl = elem('datalist');
      dl.id = id;
      document.body.appendChild(dl);
    }
    dl.innerHTML = vals.map(function (v) { return '<option value="' + String(v).replace(/"/g, '&quot;') + '"></option>'; }).join('');
    inp.setAttribute('list', id);
    return inp;
  }
  let _uid = 0;
  const nextUid = function () { return 'f' + (++_uid) + '-' + Math.random().toString(36).slice(2, 6); };

  function kindOf(schema) {
    if (!schema || typeof schema !== 'object') return 'any';
    if (schema.$ref) return 'any';                     // 本仓 schema 未用 $ref 指向其他字段
    if (schema.enum) return 'enum';
    if (has(schema, 'const')) return 'const';
    if (schema.anyOf || schema.oneOf) return 'union';
    let t = schema.type;
    if (Array.isArray(t)) t = t.filter(function (x) { return x !== 'null'; })[0] || t[0];
    return t || 'any';
  }
  function helpText(schema) {
    const parts = [];
    if (schema && schema.description) parts.push(schema.description);
    if (schema && schema.$comment) parts.push(schema.$comment);
    if (schema && schema.enum) parts.push('可选值: ' + schema.enum.join(' / '));
    else if (schema && has(schema, 'const')) parts.push('固定值: ' + JSON.stringify(schema.const));
    if (schema && (has(schema, 'minimum') || has(schema, 'maximum'))) {
      parts.push('范围: ' + (has(schema, 'minimum') ? schema.minimum : '-∞') + ' ~ ' +
                 (has(schema, 'maximum') ? schema.maximum : '+∞'));
    }
    if (schema && schema.pattern) parts.push('正则: ' + schema.pattern);
    return parts.join('　|　');
  }

  // ---------------------------------------------------------------- widgets
  /* 长文案 → 多行输入框（随内容长高，不用在小格子里横着滚） */
  function wTextarea(schema, path, ctx) {
    const ta = elem('textarea', 'ctl ta');
    ta.spellcheck = false;
    ta.rows = (schema && schema.rows) || 3;
    const v = getIn(ctx.root, path);
    ta.value = (v === undefined || v === null) ? '' : String(v);
    const minLength = schema && schema.minLength;
    /* 自适应高度：内容多了自己长高（上限 320px 后内部滚动） */
    const autosize = function () {
      if (typeof ta.scrollHeight !== 'number' || !isFinite(ta.scrollHeight)) return;
      const h = Math.min(320, Math.max((ta.rows || 3) * 19 + 12, ta.scrollHeight + 6));
      ta.style.height = h + 'px';
    };
    ta.autosize = autosize;
    autosize();
    ta.addEventListener('input', function () {
      ta.classList.toggle('bad', !!(minLength && ta.value.length < minLength));
      setIn(ctx.root, path, ta.value);
      ctx.onChange();
      autosize();
    });
    return ta;
  }

  /* 字符串数组 → 「一行一条」的多行输入（公式列表 / 名字列表的顺手写法） */
  function wLines(schema, path, ctx) {
    const wrap = elem('div', 'lines-wrap');
    const ta = elem('textarea', 'ctl ta lines');
    ta.spellcheck = false;
    ta.rows = (schema && schema.rows) || 4;
    const count = elem('span', 'lines-n', '');
    const item = (schema && schema.items) || {};
    const hints = suggestList(item, path, ctx);
    const arr0 = getIn(ctx.root, path);
    if (Array.isArray(arr0)) {
      ta.value = arr0.map(function (x) { return typeof x === 'string' ? x : JSON.stringify(x); }).join('\n');
    } else {
      ta.value = (arr0 === undefined || arr0 === null) ? '' : String(arr0);
    }
    const refresh = function () {
      const n = (Array.isArray(getIn(ctx.root, path)) ? getIn(ctx.root, path) : []).length;
      count.textContent = n ? n + ' 条' : '（空）';
    };
    refresh();
    ta.addEventListener('input', function () {
      const arr = ta.value.split('\n').map(function (s) { return s.trim(); })
        .filter(function (s) { return s !== ''; });
      if (arr.length) setIn(ctx.root, path, arr);
      else delIn(ctx.root, path);
      ctx.onChange();
      refresh();
    });
    if (hints.length) {
      const dlId = nextUid();
      const dl = elem('datalist');
      dl.id = dlId;
      dl.innerHTML = hints.map(function (v) {
        return '<option value="' + String(v).replace(/"/g, '&quot;') + '"></option>';
      }).join('');
      wrap.appendChild(dl);
      ta.setAttribute('list', dlId);
    }
    wrap.appendChild(ta);
    const foot = elem('div', 'lines-foot');
    foot.appendChild(count);
    foot.appendChild(elem('span', 'lines-tip', '一行一条 · 空行忽略'));
    wrap.appendChild(foot);
    return wrap;
  }

  /* 枚举数组 → 多选标签（勾一个加一项，取消就移除） */
  function wChips(schema, path, ctx) {
    const items = (schema && schema.items) || {};
    const opts = (items.enum || []).slice();
    const wrap = elem('div', 'chips-wrap');
    function draw() {
      wrap.innerHTML = '';
      const cur = getIn(ctx.root, path);
      const arr = Array.isArray(cur) ? cur : [];
      opts.forEach(function (val) {
        const on = arr.some(function (x) { return String(x) === String(val); });
        const b = elem('button', 'chip-pick' + (on ? ' on' : ''));
        b.type = 'button';
        b.textContent = String(val);
        b.addEventListener('click', function () {
          const now = getIn(ctx.root, path);
          let a = Array.isArray(now) ? now.slice() : [];
          const hit = a.findIndex(function (x) { return String(x) === String(val); });
          if (hit >= 0) a.splice(hit, 1);
          else a.push(val);
          if (a.length) setIn(ctx.root, path, a);
          else delIn(ctx.root, path);
          ctx.onChange();
          draw();
        });
        wrap.appendChild(b);
      });
      const cur2 = getIn(ctx.root, path);
      const extra = (Array.isArray(cur2) ? cur2 : []).filter(function (x) {
        return !opts.some(function (o) { return String(o) === String(x); });
      });
      extra.forEach(function (x) {
        const b = elem('button', 'chip-pick on bad');
        b.type = 'button';
        b.textContent = String(x) + ' ✕';
        b.title = '不在允许取值内（点击移除）';
        b.addEventListener('click', function () {
          const now = getIn(ctx.root, path) || [];
          const a = now.filter(function (y) { return String(y) !== String(x); });
          if (a.length) setIn(ctx.root, path, a); else delIn(ctx.root, path);
          ctx.onChange();
          draw();
        });
        wrap.appendChild(b);
      });
    }
    draw();
    const box = elem('div');
    box.appendChild(wrap);
    return box;
  }

  /* 0~1 的比值 → 数字 + 滑杆联动（裸小数看不出「0.35 算高还是低」） */
  function wPct(schema, path, ctx) {
    const wrap = elem('div', 'pct-wrap');
    const lo = (schema && has(schema, 'minimum')) ? schema.minimum : 0;
    const hi = (schema && has(schema, 'maximum')) ? schema.maximum : 1;
    const num = elem('input', 'ctl pct-num');
    num.type = 'number';
    num.step = '0.01';
    num.min = lo; num.max = hi;
    const rng = elem('input', 'ctl pct-rng');
    rng.type = 'range';
    rng.min = lo; rng.max = hi; rng.step = '0.01';
    const out = elem('output', 'pct-out');
    const v0 = getIn(ctx.root, path);
    const fmt = function (v) { return (v === undefined || v === null || v === '') ? '—' : Math.round(Number(v) * 100) + '%'; };
    num.value = (v0 === undefined || v0 === null) ? '' : v0;
    rng.value = (v0 === undefined || v0 === null || v0 === '') ? lo : v0;
    out.textContent = fmt(v0);
    const push = function (raw, from) {
      if (raw === '' || raw === null || raw === undefined) {
        delIn(ctx.root, path); out.textContent = '—';
        if (from !== 'num') num.value = '';
        ctx.onChange();
        return;
      }
      const n = Number(raw);
      if (Number.isNaN(n)) { num.classList.add('bad'); return; }
      num.classList.remove('bad');
      setIn(ctx.root, path, n);
      out.textContent = fmt(n);
      if (from !== 'num') num.value = n;
      if (from !== 'rng') rng.value = n;
      ctx.onChange();
    };
    num.addEventListener('input', function () { push(num.value, 'num'); });
    rng.addEventListener('input', function () { push(rng.value, 'rng'); });
    wrap.appendChild(num);
    wrap.appendChild(rng);
    wrap.appendChild(out);
    return wrap;
  }

  function wString(schema, path, ctx) {
    const inp = elem('input', 'ctl');
    inp.type = 'text';
    const v = getIn(ctx.root, path);
    inp.value = (v === undefined || v === null) ? '' : String(v);
    attachList(inp, suggestList(schema, path, ctx), nextUid());
    const minLength = schema && schema.minLength;
    inp.addEventListener('input', function () {
      inp.classList.toggle('bad', !!(minLength && inp.value.length < minLength));
      setIn(ctx.root, path, inp.value);
      ctx.onChange();
    });
    return inp;
  }

  function wEnum(schema, path, ctx) {
    const sel = elem('select', 'ctl');
    const cur = getIn(ctx.root, path);
    const opts = schema.enum.slice();
    if (cur !== undefined && opts.indexOf(cur) < 0) {
      const o = elem('option'); o.value = String(cur); o.textContent = '⚠ 非法值: ' + JSON.stringify(cur);
      sel.appendChild(o);
    } else {
      const o = elem('option'); o.value = ''; o.textContent = '（未设置）';
      sel.appendChild(o);
    }
    opts.forEach(function (v) {
      const o = elem('option'); o.value = String(v); o.textContent = String(v);
      sel.appendChild(o);
    });
    sel.value = (cur === undefined || cur === null) ? '' : String(cur);
    sel.addEventListener('change', function () {
      if (sel.value === '') delIn(ctx.root, path);
      else {
        let val = sel.value;
        // 枚举里若是数字，还原成 number（本仓枚举均为字符串，兜底处理）
        schema.enum.forEach(function (e) { if (String(e) === sel.value) val = e; });
        setIn(ctx.root, path, val);
      }
      ctx.onChange();
    });
    return sel;
  }

  function wConst(schema, path, ctx) {
    const w = elem('div');
    const cur = getIn(ctx.root, path);
    w.appendChild(elem('span', 'ctl', 'const = ' + JSON.stringify(schema.const)));
    if (cur !== undefined && cur !== schema.const) {
      w.appendChild(elem('div', 'help', '⚠ 当前值 ' + JSON.stringify(cur) + ' 不满足 const'));
    }
    return w;
  }

  function wUnion(schema, path, ctx) {
    const branches = schema.anyOf || schema.oneOf || [];
    const consts = [];
    branches.forEach(function (b) { if (b && has(b, 'const')) consts.push(b.const); });
    const inp = elem('input', 'ctl');
    inp.type = 'text';
    inp.setAttribute('list', 'union-consts-' + Math.random().toString(36).slice(2, 8));
    const dl = elem('datalist');
    dl.id = inp.getAttribute('list');
    consts.forEach(function (c) { const o = elem('option'); o.value = String(c); dl.appendChild(o); });
    const cur = getIn(ctx.root, path);
    inp.value = (cur === undefined || cur === null) ? '' : String(cur);
    inp.addEventListener('input', function () {
      const txt = inp.value.trim();
      if (txt === '') { delIn(ctx.root, path); ctx.onChange(); return; }
      let hit = null;
      consts.forEach(function (c) { if (String(c) === txt) hit = c; });
      if (hit !== null) setIn(ctx.root, path, hit);
      else if (txt !== '' && !Number.isNaN(Number(txt))) setIn(ctx.root, path, Number(txt));
      else setIn(ctx.root, path, txt);
      ctx.onChange();
    });
    const box = elem('div');
    box.appendChild(inp); box.appendChild(dl);
    const forms = branches.map(function (b) {
      if (has(b, 'const')) return JSON.stringify(b.const);
      if (b.type === 'number' || b.type === 'integer') return '数值' + (has(b, 'minimum') ? ' ≥' + b.minimum : '');
      if (b.enum) return b.enum.join('|');
      return b.type || '任意';
    });
    box.appendChild(elem('div', 'help', '允许: ' + forms.join(' 或 ')));
    return box;
  }

  function wBool(schema, path, ctx) {
    const wrap = elem('div');
    const inp = elem('input', 'ctl');
    inp.type = 'checkbox';
    inp.checked = !!getIn(ctx.root, path);
    inp.addEventListener('change', function () { setIn(ctx.root, path, inp.checked); ctx.onChange(); });
    wrap.appendChild(inp);
    return wrap;
  }

  function wNumber(schema, path, ctx) {
    const inp = elem('input', 'ctl');
    inp.type = 'number';
    inp.step = (schema && schema.type === 'integer') ? '1' : 'any';
    if (schema && has(schema, 'minimum')) inp.min = schema.minimum;
    if (schema && has(schema, 'maximum')) inp.max = schema.maximum;
    const v = getIn(ctx.root, path);
    inp.value = (v === undefined || v === null) ? '' : v;
    inp.addEventListener('input', function () {
      if (inp.value === '') { delIn(ctx.root, path); inp.classList.remove('bad'); ctx.onChange(); return; }
      const n = Number(inp.value);
      const bad = Number.isNaN(n) ||
        (schema && schema.type === 'integer' && !Number.isInteger(n)) ||
        (schema && has(schema, 'minimum') && n < schema.minimum) ||
        (schema && has(schema, 'maximum') && n > schema.maximum);
      inp.classList.toggle('bad', bad);
      setIn(ctx.root, path, n);
      ctx.onChange();
    });
    return inp;
  }

  function jsonEditor(value, onApply) {
    const ta = elem('textarea', 'ctl');
    ta.spellcheck = false;
    ta.value = JSON.stringify(value === undefined ? null : value, null, 2);
    ta.addEventListener('change', function () {
      try {
        const parsed = JSON.parse(ta.value);
        ta.classList.remove('bad');
        onApply(parsed);
      } catch (e) {
        ta.classList.add('bad');
      }
    });
    return ta;
  }

  function wArray(schema, path, ctx) {
    const items = schema.items;
    const scalar = items && (items.type === 'string' || items.type === 'number' ||
                             items.type === 'integer' || items.type === 'boolean');
    const wrap = elem('div');
    // 枚举数组 → 多选标签（比「JSON 兜底编辑」好用得多：勾一下就是一项）
    if (items && items.enum) return wChips(schema, path, ctx);
    if (!scalar) {
      wrap.appendChild(elem('div', 'help', '复杂数组 → JSON 兜底编辑'));
      wrap.appendChild(jsonEditor(getIn(ctx.root, path), function (v) {
        setIn(ctx.root, path, v); ctx.onChange(); ctx.rerender();
      }));
      return wrap;
    }
    function draw() {
      rows.innerHTML = '';
      const arr = getIn(ctx.root, path) || [];
      arr.forEach(function (_v, i) {
        const row = elem('div', 'array-row');
        const sub = renderControl(items, path.concat([i]), ctx);
        row.appendChild(sub);
        // 标量行也给联想（如 monsters.skills 每行都是真技能 key）
        if (sub && sub.tagName === 'INPUT' && sub.type === 'text') {
          attachList(sub, suggestList(items, path, ctx), nextUid());
        }
        const del = elem('button', null, '✕');
        del.title = '删除该项';
        del.addEventListener('click', function () {
          const a = getIn(ctx.root, path).slice();
          a.splice(i, 1);
          setIn(ctx.root, path, a);
          ctx.onChange(); draw(); ctx.rerender();
        });
        row.appendChild(del);
        rows.appendChild(row);
      });
      const add = elem('button', 'addbtn', '+ 添加');
      add.addEventListener('click', function () {
        const a = (getIn(ctx.root, path) || []).slice();
        a.push(items.type === 'boolean' ? false : (items.type === 'string' ? '' : 0));
        setIn(ctx.root, path, a);
        ctx.onChange(); draw(); ctx.rerender();
      });
      rows.appendChild(add);
    }
    const rows = elem('div', 'array-rows');
    draw();
    wrap.appendChild(rows);
    return wrap;
  }

  function kvEditor(schema, path, ctx) {
    const ap = schema.additionalProperties;
    const keyEnum = (schema.propertyNames && schema.propertyNames.enum) || null;
    const keyHints = suggestList(schema, path, ctx, true);
    const wrap = elem('div');
    const rows = elem('div');
    function draw() {
      rows.innerHTML = '';
      const obj = getIn(ctx.root, path) || {};
      Object.keys(obj).forEach(function (k) {
        const row = elem('div', 'kv-row');
        let kc;
        if (keyEnum) {
          kc = elem('select', 'ctl k');
          keyEnum.forEach(function (e) { const o = elem('option'); o.value = e; o.textContent = e; kc.appendChild(o); });
          kc.value = k;
        } else {
          kc = elem('input', 'ctl k'); kc.type = 'text'; kc.value = k;
          attachList(kc, keyHints, nextUid());          // 键名也联想（channels / stat_scale / judge …）
        }
        const vc = renderControl(ap, path.concat([k]), ctx);
        kc.addEventListener('change', function () {
          const obj2 = getIn(ctx.root, path);
          const newKey = kc.value;
          if (newKey !== k && newKey !== '') {
            const copy = {}; Object.keys(obj2).forEach(function (kk) { copy[kk === k ? newKey : kk] = obj2[kk]; });
            setIn(ctx.root, path, copy); ctx.onChange(); draw();
          }
        });
        const del = elem('button', null, '✕');
        del.addEventListener('click', function () { delIn(ctx.root, path.concat([k])); ctx.onChange(); draw(); ctx.rerender(); });
        row.appendChild(kc); row.appendChild(vc); row.appendChild(del);
        rows.appendChild(row);
      });
      const add = elem('button', 'addbtn', '+ 添加键');
      add.addEventListener('click', function () {
        const obj2 = getIn(ctx.root, path) || {};
        let nk = 'new_key', i = 1;
        while (has(obj2, nk)) { nk = 'new_key' + (i++); }
        if (keyEnum) { for (const e of keyEnum) { if (!has(obj2, e)) { nk = e; break; } } }
        setIn(ctx.root, path.concat([nk]), ap && ap.type === 'integer' ? 0 : '');
        ctx.onChange(); draw(); ctx.rerender();
      });
      rows.appendChild(add);
    }
    draw();
    wrap.appendChild(rows);
    return wrap;
  }

  // ------------------------------------------------------------ dispatch
  function renderControl(schema, path, ctx) {
    // ① 调用方指定的控件形态（按字段语义：长文案 / 一行一条 / 比值 / 多选）
    const w = widgetOf(schema, path, ctx);
    if (w === 'textarea') return wTextarea(schema, path, ctx);
    if (w === 'lines' && kindOf(schema) === 'array') return wLines(schema, path, ctx);
    if (w === 'chips' && kindOf(schema) === 'array') return wChips(schema, path, ctx);
    if (w === 'pct' && (kindOf(schema) === 'number' || kindOf(schema) === 'integer')) {
      return wPct(schema, path, ctx);
    }
    // ② schema 自带的长文本启发（maxLength 很大 = 明显是文案，不是代号）
    if (kindOf(schema) === 'string' && schema && schema.maxLength >= 120) {
      return wTextarea(schema, path, ctx);
    }
    switch (kindOf(schema)) {
      case 'enum': return wEnum(schema, path, ctx);
      case 'const': return wConst(schema, path, ctx);
      case 'union': return wUnion(schema, path, ctx);
      case 'boolean': return wBool(schema, path, ctx);
      case 'integer': case 'number': return wNumber(schema, path, ctx);
      case 'object': return objControl(schema, path, ctx);
      case 'array': return wArray(schema, path, ctx);
      case 'string': return wString(schema, path, ctx);
      default:
        return jsonEditor(getIn(ctx.root, path), function (v) {
          setIn(ctx.root, path, v); ctx.onChange(); ctx.rerender();
        });
    }
  }

  function field(schema, keyLabel, path, ctx, opts) {
    const f = elem('div', 'field');
    f.dataset.path = path.join('.');
    if (opts && opts.required) f.dataset.required = '1';
    const lab = elem('label', 'f-label');
    if (schema && schema.title && schema.title !== keyLabel) {
      lab.appendChild(elem('span', 'f-title', schema.title));
      lab.appendChild(document.createTextNode(' (' + keyLabel + ')'));
    } else {
      lab.textContent = keyLabel;
    }
    if (opts && opts.required) lab.appendChild(elem('span', 'req', '*'));
    f.appendChild(lab);
    f.appendChild(renderControl(schema || {}, path, ctx));
    const h = helpText(schema);
    if (h) f.appendChild(elem('div', 'help', h));
    return f;
  }

  function objControl(schema, path, ctx) {
    const props = schema.properties || null;
    const ap = schema.additionalProperties;
    if (!props || Object.keys(props).length === 0) {
      if (ap && typeof ap === 'object') return kvEditor(schema, path, ctx);
      const wrap = elem('div');
      wrap.appendChild(elem('div', 'help', '自由结构对象 → JSON 兜底编辑'));
      wrap.appendChild(jsonEditor(getIn(ctx.root, path), function (v) {
        setIn(ctx.root, path, v); ctx.onChange(); ctx.rerender();
      }));
      return wrap;
    }
    const fs = elem('fieldset', 'grp');
    const lg = elem('legend', null, (schema.title || '字段') + (path.length ? ' (' + path[path.length - 1] + ')' : ''));
    fs.appendChild(lg);
    const required = schema.required || [];
    Object.keys(props).forEach(function (k) {
      fs.appendChild(field(props[k], k, path.concat([k]), ctx, { required: required.indexOf(k) >= 0 }));
    });
    // schema 未声明的现存字段（数据允许 additionalProperties）→ JSON 兜底
    const val = getIn(ctx.root, path);
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      const extraKeys = Object.keys(val).filter(function (k) { return !has(props, k); });
      if (extraKeys.length) {
        const det = elem('details', 'extra');
        const sum = elem('summary', null, '其他字段（schema 未声明，' + extraKeys.length + ' 项）');
        det.appendChild(sum);
        const sub = {};
        extraKeys.forEach(function (k) { sub[k] = val[k]; });
        det.appendChild(jsonEditor(sub, function (parsed) {
          extraKeys.forEach(function (k) { delIn(ctx.root, path.concat([k])); });
          Object.keys(parsed).forEach(function (k) { setIn(ctx.root, path.concat([k]), parsed[k]); });
          ctx.onChange(); ctx.rerender();
        }));
        fs.appendChild(det);
      }
    }
    return fs;
  }

  // -------------------------------------------------------------- public
  /* 分组：把 [{id,label,icon,fields}] 规整成可用形态（无有效组 → null = 平铺渲染） */
  function normalizeGroups(groups, keys) {
    if (!Array.isArray(groups) || !groups.length) return null;
    const out = (groups || []).map(function (g) {
      return {
        id: String((g && g.id) || ''),
        label: String((g && g.label) || (g && g.id) || ''),
        icon: String((g && g.icon) || ''),
        fields: ((g && g.fields) || []).filter(function (k) { return keys.indexOf(k) >= 0; }),
      };
    }).filter(function (g) { return g.fields.length > 0; });
    return out.length ? out : null;
  }

  function catGroup(g, ctx, mkField, opts, container) {
    const fs = elem('fieldset', 'grp cat');
    fs.dataset.group = g.id;
    const lg = elem('legend', 'cat-legend');
    lg.appendChild(elem('span', 'cat-ico', g.icon || '•'));
    lg.appendChild(elem('span', 'cat-name', g.label));
    lg.appendChild(elem('span', 'cat-n', String(g.fields.length)));
    lg.title = '点击折叠 / 展开这一组';
    fs.appendChild(lg);
    g.fields.forEach(function (k) { fs.appendChild(mkField(k)); });
    const key = ((opts && opts.groupKey) || '') + '#' + g.id;
    if (opts && opts.collapsed && opts.collapsed(key)) fs.classList.add('collapsed');
    lg.addEventListener('click', function () {
      fs.classList.toggle('collapsed');
      if (opts && opts.onToggleGroup) opts.onToggleGroup(key, fs.classList.contains('collapsed'));
    });
    container.appendChild(fs);
    return fs;
  }

  function render(rootSchema, rootValue, opts) {
    const ctx = {
      root: rootValue,
      onChange: (opts && opts.onChange) || function () {},
      rerender: function () { if (opts && opts.onRerender) opts.onRerender(); },
      // 控件形态 + 联想（透传给每个控件；不传 = 全部按 schema 类型默认渲染）
      widget: (opts && opts.widget) || null,
      suggest: (opts && opts.suggest) || null,
      suggestKey: (opts && opts.suggestKey) || null
    };
    const container = elem('div', 'schema-form');
    const fields = rootSchema.properties || {};
    const required = rootSchema.required || [];
    const keys = Object.keys(fields);
    const mkField = function (k) {
      return field(fields[k], k, [k], ctx, { required: required.indexOf(k) >= 0 });
    };
    const groups = normalizeGroups(opts && opts.groups, keys);
    // 根对象：无分组 → 直接铺字段（旧行为）；有分组 → 每组一个 fieldset（沿用 .grp 样式）
    if (!groups) {
      keys.forEach(function (k) { container.appendChild(mkField(k)); });
    } else {
      const placed = {};
      groups.forEach(function (g) {
        const rel = g.fields.filter(function (k) { return !placed[k]; });
        if (!rel.length) return;
        rel.forEach(function (k) { placed[k] = true; });
        catGroup({ id: g.id, label: g.label, icon: g.icon, fields: rel }, ctx, mkField, opts, container);
      });
      const rest = keys.filter(function (k) { return !placed[k]; });
      if (rest.length) {
        catGroup({ id: '_rest', label: '未分组', icon: '❓', fields: rest }, ctx, mkField, opts, container);
      }
    }
    if (rootValue && typeof rootValue === 'object') {
      const extra = Object.keys(rootValue).filter(function (k) { return !has(fields, k); });
      if (extra.length) {
        const det = elem('details', 'extra');
        det.appendChild(elem('summary', null, '其他字段（schema 未声明，' + extra.length + ' 项）'));
        const sub = {};
        extra.forEach(function (k) { sub[k] = rootValue[k]; });
        det.appendChild(jsonEditor(sub, function (parsed) {
          extra.forEach(function (k) { delIn(rootValue, [k]); });
          Object.keys(parsed).forEach(function (k) { setIn(rootValue, [k], parsed[k]); });
          ctx.onChange(); ctx.rerender();
        }));
        container.appendChild(det);
      }
    }
    return { el: container, root: rootValue, rerender: ctx.rerender };
  }

  function markErrors(container, errors) {
    container.querySelectorAll('.field.has-error').forEach(function (e) { e.classList.remove('has-error'); });
    (errors || []).forEach(function (e) {
      let p = String(e.path || '').replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '.$1');
      if (!p) return;
      const node = container.querySelector('.field[data-path="' + p.replace(/"/g, '\\"') + '"]');
      if (node) node.classList.add('has-error');
    });
  }

  return { render: render, markErrors: markErrors, kindOf: kindOf, getIn: getIn, setIn: setIn };
})();
