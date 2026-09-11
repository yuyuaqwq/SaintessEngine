/* schema_form.js —— JSON Schema → 表单渲染器（原生 DOM，零依赖）
 *
 * 渲染规则（EDITOR_SPEC.md「表单渲染规则」）：
 *   string + enum            → <select>
 *   string                   → <input type=text>
 *   number / integer         → <input type=number>（带 min/max/step）
 *   boolean                  → <checkbox>
 *   object（有 properties）   → 折叠分组（递归渲染）
 *   object（仅 additionalProperties schema）→ 键值行编辑器（键为 propertyNames.enum 时用 select）
 *   array（元素为标量）        → 可增删的行列表
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
  function wString(schema, path, ctx) {
    const inp = elem('input', 'ctl');
    inp.type = 'text';
    const v = getIn(ctx.root, path);
    inp.value = (v === undefined || v === null) ? '' : String(v);
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
    if (!scalar || items.enum) {
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
      rerender: function () { if (opts && opts.onRerender) opts.onRerender(); }
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
