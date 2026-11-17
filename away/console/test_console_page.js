// test_console_page.js -- offline test of console.html in node (no browser, no network).
// Runs the page's two scripts against a tiny fake page + fake fetch, with fake /console.json snapshots.
//   node test_console_page.js        -> prints PASS/FAIL lines and a total; exit code 1 if anything failed
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const html = fs.readFileSync(path.join(__dirname, 'console.html'), 'utf8');
let passed = 0, failed = 0;
function ok(cond, what) { if (cond) { passed++; } else { failed++; console.log('FAIL', what); } }
function eq(a, b, what) { ok(JSON.stringify(a) === JSON.stringify(b), what + ' -- got ' + JSON.stringify(a) + ' want ' + JSON.stringify(b)); }

// ---- a very small fake page ------------------------------------------------------------------------------
function El(tag) {
  const e = {tag, children: [], attrs: {}, style: {}, listeners: {}, className: '', textContent: '', value: '', parent: null};
  e.classList = {
    toggle(c, on) { const s = new Set(e.className.split(' ').filter(Boolean)); on ? s.add(c) : s.delete(c); e.className = [...s].join(' '); },
    contains(c) { return e.className.split(' ').includes(c); }
  };
  Object.defineProperty(e, 'firstChild', {get() { return e.children[0] || null; }});
  e.appendChild = c => { c.parent = e; e.children.push(c); return c; };
  e.removeChild = c => { e.children.splice(e.children.indexOf(c), 1); return c; };
  e.setAttribute = (k, v) => { e.attrs[k] = String(v); };
  e.addEventListener = (k, f) => { (e.listeners[k] = e.listeners[k] || []).push(f); };
  e.fire = k => (e.listeners[k] || []).map(f => f());
  return e;
}
function makePage() {
  const byId = {};
  for (const m of html.matchAll(/id="([a-z]+)"/g)) byId[m[1]] = El('x');
  byId.audio.value = '60';
  return {getElementById: id => byId[id] || null, createElement: t => El(t), byId};
}
function makeFetch(routes) {
  const calls = [];
  const f = (url, opts) => {
    calls.push({url, opts: opts || {}});
    const r = typeof routes[url] === 'function' ? routes[url](opts) : routes[url];
    if (!r) return Promise.resolve({ok: false, status: 404, text: () => Promise.resolve('Unknown look.')});
    return Promise.resolve({ok: r.status === 200, status: r.status,
      text: () => Promise.resolve(r.text || ''), json: () => Promise.resolve(r.json)});
  };
  f.calls = calls;
  return f;
}
const scripts = [...html.matchAll(/<script id="(\w+)">([\s\S]*?)<\/script>/g)].reduce((o, m) => (o[m[1]] = m[2], o), {});
ok(scripts.logic && scripts.ui, 'both scripts found');
function boot(routes) {
  const doc = makePage(), fetch = makeFetch(routes), timers = [];
  const ctx = {document: doc, fetch, setInterval: (f, ms) => timers.push(['int', ms]), setTimeout: (f, ms) => timers.push(['to', ms, f]),
               console, Date, Math, JSON, Promise, Set, Array, String, parseFloat, isFinite, Object};
  vm.createContext(ctx);
  vm.runInContext(scripts.logic, ctx);
  vm.runInContext(scripts.ui, ctx);
  return {ctx, doc, fetch, timers, $: id => doc.byId[id]};
}
const tick = () => new Promise(r => setImmediate(r));

// ---- fake /console.json snapshots (shapes copied from hub_modes.Director.status + console_route.snapshot) ----
const ZONES = [{id: '1A', heads: [], lamps: 2}, {id: '1B', heads: [3], lamps: 1}, {id: '2A', heads: [5], lamps: 1},
               {id: '2B', heads: [2], lamps: 0}, {id: '3A', heads: [], lamps: 2}];
function showSnap(over) {
  return Object.assign({ok: true, hub: true, look: 'show', since: '21:04', busy: false, guest: false, level: 0.42, tempo: 124.2,
    section: 'groove', audio: 'listening',
    saved: {dmx_pattern: 'modes', show_lock: '', show_wave: 'forward', show_loop_dir: 'cw', zone_order: ['1A', '1B', '2A', '2B', '3A']},
    show: {on: true, pattern: 'modes', act: 'zones', act_name: 'Zone modes', mode: 'wave', name: 'Wave', bar: 3, bars: 8,
           lock: '', speed: 1.5, audio_mix: 0.75, acts_on: true, section: 'groove', zones: ZONES,
           head_out: {'3': [0.9, 0.5, 0.4], '5': [0.3, 0.2, 0.1], '2': [0.0, -1, -1]},
           acts: [], modes: [], history: []}}, over || {});
}
const OFF = {ok: true, hub: false, show: null, level: null, tempo: null, section: null, look: 'purple', since: '19:00', guest: false,
             saved: {dmx_pattern: 'modes', show_lock: 'gobos', show_wave: 'back', show_audio: 0.25, show_speed: 0.75,
                     show_acts: false, zone_order: ['1A', '1B', '2A', '2B', '3A']}};

(async () => {
  // ---- pure logic ----
  const L = boot({'console.json': {status: 200, json: OFF}}).ctx;
  let v = L.view(showSnap());
  eq([v.hub, v.running, v.title, v.sub, v.bar, v.bars, v.section], [true, true, 'Wave', 'Zone modes', 3, 8, 'groove'], 'running show readout');
  eq([v.act, v.mode, v.lockKind, v.wave, v.loop, v.audio, v.speed, v.actsOn, v.level, v.tempo],
     ['zones', 'wave', 'auto', 'forward', 'cw', 75, 1.5, true, 0.42, 124], 'running show controls');
  eq(v.zones.map(z => [z.id, z.lvl]), [['1A', 0], ['1B', 0.9], ['2A', 0.3], ['2B', 0], ['3A', 0]], 'zone level = its heads');
  v = L.view(showSnap({show: Object.assign(showSnap().show, {act: 'gobos', act_name: 'Gobos', mode: 'wave', lock: 'gobos'})}));
  eq([v.title, v.sub, v.act, v.mode, v.lockKind], ['Gobos', 'Act', 'gobos', null, 'act'], 'act playing + act lock');
  v = L.view(showSnap({show: Object.assign(showSnap().show, {lock: 'Orbit '})}));
  eq([v.lock, v.lockKind], ['orbit', 'mode'], 'mode lock (case/space tolerant)');
  eq(L.view(showSnap({show: Object.assign(showSnap().show, {lock: 'whatever'})})).lockKind, 'other', 'unknown lock shown as other');
  v = L.view(OFF);
  eq([v.hub, v.running, v.title, v.lock, v.lockKind, v.wave, v.loop, v.audio, v.speed, v.actsOn, v.level, v.section],
     [false, false, 'Hub off', 'gobos', 'act', 'back', 'alternate', 25, 0.75, false, null, ''], 'hub off uses saved settings');
  eq(v.zones.map(z => [z.id, z.heads]), [['1A', null], ['1B', null], ['2A', null], ['2B', null], ['3A', null]], 'hub off: zone ids only, no guessed heads');
  v = L.view(showSnap({show: Object.assign(showSnap().show, {on: false, pattern: 'normal'})}));
  eq([v.title, v.director, v.bar], ['Director off', false, 0], 'director off');
  eq(L.view(showSnap({show: Object.assign(showSnap().show, {on: false})})).title, 'Waiting for the show', 'director idle');
  for (const junk of [null, undefined, 'x', 5, {show: 'x', saved: 7}, {hub: true, show: {on: true, bar: 'NaN', bars: -3, zones: [{id: 1}], head_out: 'x'}}]) {
    let threw = false; try { L.view(junk); } catch (e) { threw = e.message; }
    eq(threw, false, 'view survives junk ' + JSON.stringify(junk));
  }
  eq(L.view({hub: true, show: {on: true, bar: 99, bars: 8}}).bar, 8, 'bar clamped to bars');
  // taps -> /show/set bodies
  eq(L.body('lock', 'wave'), {show_lock: 'wave'}, 'lock mode');
  eq(L.body('lock', 'uv'), {show_lock: 'uv'}, 'lock act');
  eq(L.body('lock', 'strobe'), null, 'lock rejects unknown');
  eq(L.body('auto'), {show_lock: ''}, 'auto unlocks');
  eq(L.body('wave', 'alternate'), {show_wave: 'alternate'}, 'wave');
  eq(L.body('wave', 'sideways'), null, 'wave rejects unknown');
  eq(L.body('loop', 'ccw'), {show_loop_dir: 'ccw'}, 'loop');
  eq(L.body('loop', 'up'), null, 'loop rejects unknown');
  eq([L.body('audio', '35'), L.body('audio', 250), L.body('audio', -4), L.body('audio', 'x')],
     [{show_audio: 0.35}, {show_audio: 1}, {show_audio: 0}, {show_audio: 0.6}], 'audio slider 0-100 -> 0-1');
  eq([L.body('speed', 0.75), L.body('speed', 9), L.body('speed', 0.1)], [{show_speed: 0.75}, {show_speed: 2}, {show_speed: 0.5}], 'speed clamped');
  eq([L.body('acts', true), L.body('acts', false)], [{show_acts: true}, {show_acts: false}], 'acts on/off');
  eq([L.body('director', true), L.body('director', false)], [{dmx_pattern: 'modes'}, {dmx_pattern: 'normal'}], 'director');
  eq(L.body('strobe', 1), null, 'unknown kind ignored');
  // every key the page can send is a /show/set key (python test checks them against rig_control's allowlist)
  const keys = new Set();
  [['lock', 'wave'], ['auto'], ['wave', 'back'], ['loop', 'cw'], ['audio', 5], ['speed', 1], ['acts', 1], ['director', 1]]
    .forEach(a => Object.keys(L.body(...a)).forEach(k => keys.add(k)));
  fs.writeFileSync(path.join(__dirname, '.page_keys.txt'), [...keys].sort().join('\n') + '\n' + L.QUICK.map(q => 'look:' + q[0]).join('\n') + '\n');

  // ---- the page itself (fake page + fake fetch) ----
  let t = boot({'console.json': {status: 200, json: showSnap({show: Object.assign(showSnap().show, {lock: 'wave'})})},
                'show/set': {status: 200, text: 'Set: show_lock'}, 'heads_off': {status: 200, text: 'Moving heads parking, then power off, coming up.'}});
  await tick(); await tick(); await tick();
  eq(t.timers.filter(x => x[0] === 'int').map(x => x[1]), [1000], 'polls every 1 s');
  eq(t.fetch.calls[0].url, 'console.json', 'first call reads console.json');
  eq(t.$('title').textContent, 'Wave', 'title painted');
  eq(t.$('bar').textContent, '3/8', 'bar x/8 painted');
  eq(t.$('bars').children.map(c => c.className), ['past', 'past', 'on', '', '', '', '', ''], 'bar strip');
  eq([t.$('section').textContent, t.$('level').textContent, t.$('tempo').textContent, t.$('meter').style.width], ['groove', '42%', '124', '42%'], 'stats');
  eq(t.$('audio').value, '75', 'slider follows live audio mix');
  eq(t.$('conn').className, 'num', 'connection ok');
  const btnBy = label => { const all = []; const walk = e => { if (e.tag === 'button') all.push(e); e.children.forEach(walk); };
    Object.values(t.doc.byId).forEach(walk); return all.find(b => b.textContent === label); };
  ok(btnBy('Wave').classList.contains('on') && btnBy('Wave').classList.contains('play'), 'locked + playing mode button lit');
  ok(!btnBy('Auto').classList.contains('on'), 'auto off while locked');
  ok(btnBy('Forward').classList.contains('on') && btnBy('CW').classList.contains('on') && btnBy('1.5×').classList.contains('on'), 'wave/loop/speed lit');
  eq(t.$('zones').children.map(z => z.attrs['data-z'] + ':' + z.children[1].textContent), ['1A:lamps only', '1B:Head 3', '2A:Head 5', '2B:Head 2', '3A:lamps only'], 'zone map with heads');
  eq(t.$('zones').children.map(z => [z.style.gridColumn, z.style.gridRow]), [['1', '1'], ['1', '2'], ['2', '1'], ['2', '2'], ['3', '1']], 'zone map layout');
  ok(t.$('zones').children[1].classList.contains('lit') && !t.$('zones').children[2].classList.contains('lit'), 'busy zone lit');
  eq(btnBy('Hue showcase') !== undefined && btnBy('Burst (drop)') !== undefined && btnBy('Relay') !== undefined, true, 'all acts + modes have buttons');
  // tap a mode -> POST /show/set
  const n0 = t.fetch.calls.length;
  btnBy('Orbit').fire('click'); await tick(); await tick(); await tick();
  const post = t.fetch.calls[n0];
  eq([post.url, post.opts.method, JSON.parse(post.opts.body)], ['show/set', 'POST', {show_lock: 'orbit'}], 'tap Orbit locks it');
  eq(t.$('msg').textContent, 'Set: show_lock', 'reply shown');
  btnBy('Auto').fire('click'); await tick();
  eq(JSON.parse(t.fetch.calls.filter(c => c.url === 'show/set').pop().opts.body), {show_lock: ''}, 'Auto unlocks');
  t.$('audio').value = '30'; t.$('audio').fire('input'); t.$('audio').fire('change'); await tick();
  eq(JSON.parse(t.fetch.calls.filter(c => c.url === 'show/set').pop().opts.body), {show_audio: 0.3}, 'slider sends on release');
  btnBy('Modes only').fire('click'); await tick();
  eq(JSON.parse(t.fetch.calls.filter(c => c.url === 'show/set').pop().opts.body), {show_acts: false}, 'acts off');
  // heads off needs two taps
  const h0 = t.fetch.calls.filter(c => c.url === 'heads_off').length;
  btnBy('Heads off').fire('click'); await tick();
  eq(t.fetch.calls.filter(c => c.url === 'heads_off').length, h0, 'heads off: first tap only arms');
  ok(btnBy('Heads off').classList.contains('arm'), 'armed look shown');
  btnBy('Heads off').fire('click'); await tick(); await tick();
  eq(t.fetch.calls.filter(c => c.url === 'heads_off').length, h0 + 1, 'heads off: second tap sends');
  btnBy('Purple').fire('click'); await tick(); await tick();
  eq(t.fetch.calls.filter(c => c.url === 'purple').length, 1, 'purple: one tap');
  eq(t.$('msg').className, 'bad', 'unknown route reply shown as error');
  ok(t.fetch.calls.every(c => !/^https?:|\/\//.test(c.url)), 'only relative same-origin calls');
  ok(t.fetch.calls.every(c => c.opts.credentials === 'same-origin'), 'cookie login on every call');

  // hub off page
  t = boot({'console.json': {status: 200, json: OFF}}); await tick(); await tick(); await tick();
  eq([t.$('title').textContent, t.$('bar').textContent, t.$('level').textContent], ['Hub off', '-', '-'], 'hub off painted');
  eq(t.$('zones').children.map(z => z.children[1].textContent), ['', '', '', '', ''], 'hub off: no head guesses');
  // not signed in
  t = boot({'console.json': {status: 403}}); await tick(); await tick(); await tick();
  ok(t.$('conn').className.includes('down') && t.$('conn').textContent.startsWith('Not signed in'), '403 -> sign-in hint');
  // empty zone map
  t = boot({'console.json': {status: 200, json: {hub: false, saved: {}}}}); await tick(); await tick(); await tick();
  eq(t.$('zones').children.map(z => z.textContent), ['No zone map yet'], 'no zones note');

  // ---- design rules (Michael: no AI-slop) ----
  ok(!/gradient|backdrop-filter|blur\(/i.test(html), 'no gradients / glass');
  ok(!/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u.test(html), 'no emoji');
  ok(!/(src|href)=["']?https?:/i.test(html) && !/fetch\(['"]https?:/.test(html), 'no outside files or hosts');
  const colours = new Set((html.match(/#[0-9a-f]{6}\b/gi) || []).map(c => c.toLowerCase()));
  ok(colours.has('#9b5cff') && ![...colours].some(c => ['#ffffff', '#ffbf00', '#ffb000'].includes(c)), 'one purple accent, no white/amber colour');
  console.log((failed ? 'FAILED ' : 'PASSED ') + passed + '/' + (passed + failed));
  process.exit(failed ? 1 : 0);
})().catch(e => { console.log('CRASH', e.stack); process.exit(1); });
