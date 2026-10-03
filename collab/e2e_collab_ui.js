#!/usr/bin/env node
/**
 * e2e_collab_ui.js —— 协作台界面端到端回归（界面侧维护 ✓ 可复跑 ✓）
 *
 * ⭐ 为什么入库：电脑侧 `PC-…-117` §四 指出「你方自报 E2E 19/0，但仓库里没有脚本 → 不可复跑 ✗」✓
 *    → 本文件即为**入库版** ✓（此前只在我方工作区 ✓）
 *
 * 【依赖】Node + Playwright（本机为全局安装，非仓库依赖）
 *   NODE_PATH 需指向全局 node_modules：
 *     Windows:  set NODE_PATH=%APPDATA%\npm\node_modules
 *     macOS/Linux: export NODE_PATH=$(npm root -g)
 *
 * 【用法】
 *   1) 先起协作台（另开一个终端）：
 *        python collab/relay_server.py --log %TEMP%\e2e.jsonl --port 8899 --demo-provider --enable-actions --issue-title E2E
 *        ⭐ 带 `--enable-actions` 是为了能用 `#btn-step` 造数据 ✓（否则【4】的 data-layer 断言会因无数据而空 ✗）
 *   2) 再跑本脚本：
 *        node collab/e2e_collab_ui.js 8899
 *      或指定根目录：  node collab/e2e_collab_ui.js 8899 --repo .
 *
 * 【退出码】0 = 全绿 ✓ ｜ 1 = 有断言失败 ✗ ｜ 2 = 环境错误
 *
 * 【覆盖】项目层接线 / 角色条 / 资产矩阵（三勾）/ 单角色列表 / 设绑定载荷形状 / 真三态 / 不回归
 * 【边界】⛔ 本脚本**只读** ✓（只点界面、只投递待办 ✓ 不跑运行器 ✗ 不改仓库 ✗）
 *         ⚠️ 它会往 collab/pending/ 投递 1 条待办（用于验"待办/真三态"）→ 请自行清理 ✓
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const PORT = parseInt(process.argv[2] || '8899', 10);
const BASE = `http://127.0.0.1:${PORT}/`;
const repoArg = process.argv.indexOf('--repo');
const REPO = repoArg >= 0 ? path.resolve(process.argv[repoArg + 1] || '.') : path.resolve(__dirname, '..');
const PEND = path.join(REPO, 'collab', 'pending');

const P = [], F = [];
const ok = (n, c, e) => {
  const l = n + (e !== undefined ? ' ｜ ' + JSON.stringify(e) : '');
  (c ? P : F).push(l);
  console.log((c ? '  ✅ ' : '  ❌ ') + l);
};
const sec = (t) => console.log('\n' + '='.repeat(70) + '\n' + t + '\n' + '='.repeat(70));

(async () => {
  const before = fs.existsSync(PEND) ? fs.readdirSync(PEND) : [];
  const br = await chromium.launch();
  const pg = await br.newPage({ viewport: { width: 1400, height: 950 } });
  const bad404 = [];
  pg.on('response', r => { if (r.status() >= 400) bad404.push(r.status() + ' ' + r.url()); });

  await pg.goto(BASE, { waitUntil: 'load' });
  await pg.waitForTimeout(1200);

  // ⭐ 先造数据：否则【4】的"行级 data-layer 契约仍在"会因 0 行而**空断言/误红** ✗
  //   （本脚本第一版就踩了这个 ✓ —— 断言之前先证明"有东西可断言" ✓）
  for (let i = 0; i < 3; i++) { try { await pg.click('#btn-step', { timeout: 800 }); await pg.waitForTimeout(700); } catch (e) { break; } }
  await pg.waitForTimeout(1000);
  const seeded = await pg.locator('[data-seq]').count();
  console.log('   （已造数据：data-seq 行数 = %d）', seeded);

  sec('【1】项目层接线');
  const s1 = await pg.evaluate(() => ({
    proj: (document.getElementById('proj-sel') || {}).textContent,
    chips: document.querySelectorAll('#proj-chips .pchip').length,
    roles: document.querySelectorAll('#rail-list .role').length,
    editBtn: !!document.getElementById('btn-proj-edit'),
    matrixBtn: !!document.getElementById('btn-matrix')
  }));
  ok('当前项目名已渲染', !!s1.proj && s1.proj !== '—', { proj: s1.proj });
  ok('项目 chips ≥ 1', s1.chips >= 1, s1);
  ok('角色条已渲染', s1.roles >= 1, { roles: s1.roles });
  ok('✎ 编辑项目 入口在', s1.editBtn, s1);
  ok('▦ 资产矩阵 入口在', s1.matrixBtn, s1);

  sec('【2】资产矩阵（三勾 / 过滤 / 单角色）');
  await pg.click('#btn-matrix'); await pg.waitForTimeout(1400);
  const s2 = await pg.evaluate(() => ({
    open: document.getElementById('mxpanel').classList.contains('on'),
    rows: document.querySelectorAll('#mx-table tbody tr').length,
    ticksOn: document.querySelectorAll('#mx-table .tick b.on').length,
    stat: (document.getElementById('mx-stat') || {}).innerText,
    fake: [].slice.call(document.querySelectorAll('#mx-table tbody th.rh')).map(e => e.textContent).filter(t => t.charAt(0) === '_')
  }));
  ok('矩阵面板已打开', s2.open, { stat: s2.stat });
  ok('已读到资产（行 ≥ 1）', s2.rows >= 1, { rows: s2.rows });
  ok('三勾有 on（数据真读到）', s2.ticksOn > 0, { on: s2.ticksOn });
  ok('已过滤 `_` 开头伪角色', s2.fake.length === 0, { fake: s2.fake });
  await pg.fill('#mx-filter', 'idle'); await pg.waitForTimeout(500);
  const s2b = await pg.evaluate(() => [].slice.call(document.querySelectorAll('#mx-table thead th')).map(e => e.textContent).slice(1, -1));
  ok('状态筛选生效（只剩含 idle 的列）', s2b.length > 0 && s2b.every(n => n.toLowerCase().indexOf('idle') >= 0), { cols: s2b });
  await pg.fill('#mx-filter', ''); await pg.waitForTimeout(400);
  await pg.click('.tb2[data-mxmode="single"]'); await pg.waitForTimeout(700);
  const s2c = await pg.evaluate(() => ({
    single: document.getElementById('mx-single').style.display !== 'none',
    rows: document.querySelectorAll('#mx-single .sli').length
  }));
  ok('单角色列表可切换且有行', s2c.single && s2c.rows > 0, s2c);
  await pg.click('.tb2[data-mxmode="matrix"]'); await pg.waitForTimeout(500);

  sec('【3】设绑定（set_portrait）载荷形状');
  const s3 = await pg.evaluate(() => ({
    roles: [].slice.call(document.querySelectorAll('#mx-bind-role option')).map(o => o.value),
    prefixes: [].slice.call(document.querySelectorAll('#mx-bind-prefix option')).map(o => o.value)
  }));
  ok('角色下拉取自 /api/roles', s3.roles.length >= 1, { roles: s3.roles });
  ok('前缀下拉取自 /api/assets（含池子）', s3.prefixes.length >= 1, { n: s3.prefixes.length });
  await pg.selectOption('#mx-bind-role', s3.roles[0]);
  if (s3.prefixes.length) { await pg.selectOption('#mx-bind-prefix', s3.prefixes[0]); }
  await pg.click('#mx-op-setportrait');
  // ⭐ 改成**轮询等待**（原来固定等 1400ms —— 实测偶发不足 → 误报 ✗；不当“碰巧通过”✓）
  let s3b = '';
  for (let i = 0; i < 20; i++) {
    await pg.waitForTimeout(300);
    s3b = await pg.evaluate(() => document.getElementById('mx-state').textContent);
    if (String(s3b).indexOf('已投递') >= 0 || String(s3b).indexOf('被拒') >= 0) { break; }
  }
  ok('提示须人跑运行器（不假装成功）', String(s3b).indexOf('run_pending') >= 0, { txt: String(s3b).slice(0, 120) });
  const after = fs.existsSync(PEND) ? fs.readdirSync(PEND) : [];
  const created = after.filter(f => !before.includes(f) && f.endsWith('.json'));
  ok('待办文件已产生', created.length >= 1, { created });
  if (created.length) {
    const j = JSON.parse(fs.readFileSync(path.join(PEND, created[0]), 'utf8'));
    ok('载荷 = {role, op:set_portrait, portrait_prefix}（⛔ 无 state）',
       j.payload && j.payload.op === 'set_portrait' && 'portrait_prefix' in j.payload && !('state' in j.payload), j.payload);
  }

  sec('【4】不回归：面板系统 / 契约 / 无 404');
  const s4 = await pg.evaluate(() => ({
    panels: ['panel-l1', 'panel-l2', 'panel-l3'].filter(id => document.getElementById(id)).length,
    rows: document.querySelectorAll('[data-seq]').length,
    hasDataLayer: !!document.querySelector('[data-layer]')
  }));
  ok('三面板仍在', s4.panels === 3, s4);
  if (s4.rows === 0) {
    // ⭐ 无数据时**明报跳过** ✗（不把空断言当通过 ✓）
    console.log('  ⚠️ 跳过：行级 data-layer（当前 0 行数据 → 无法断言；请带 --enable-actions 起服务 ✓）');
  } else {
    ok('行级 data-layer 契约仍在', s4.hasDataLayer, s4);
  }
  // ⭐ 批 4b-4 升级：探针**未上线** → ⛔ 一个图片请求都不发 ✓（只允许 1 条＝探针自身 ✓）
  //    ⚠️ 旧版只筛 `assets_3.0` ✗ → 探针的 `/api/thumb` 404 漏过 ✗ ＝“跛脚断言” ✗（本轮改严 ✓）
  const thumbReqs = bad404.filter(u => u.indexOf('/api/thumb') >= 0);
  const otherBad = bad404.filter(u => u.indexOf('/api/thumb') < 0 && u.indexOf('assets_3.0') >= 0);
  const mxImgs = await pg.locator('img.mthumb').count();
  const pvImgs = await pg.locator('img.mbig').count();
  const mxMsg = await pg.locator('#mx-state').innerText().catch(() => '');
  const tnMsg = await pg.locator('#thumb-note').innerText().catch(() => '');
  ok('⭐ 探针至多 1 条（端点未上线 → 不进图片面 ✓）', thumbReqs.length <= 1, { thumbReqs });
  ok('⛔ 矩阵零缩略图 img（未上线 → 不假装 ✓）', mxImgs === 0 && pvImgs === 0, { mxImgs, pvImgs });
  ok('⛔ 无 assets_3.0 图片 404', otherBad.length === 0, { otherBad });
  // ⭐ 提示必须**常驻**（旧版寄在 `#mx-state` ✗ → 被投递文案覆掉 ✗ ＝“自以为写了提示” ✗）
  ok('⭐ 常驻明示“端点未上线”（不静默 ✓）', /端点未上线/.test(tnMsg), { tnMsg: tnMsg.slice(0, 120), mxMsg: mxMsg.slice(0, 40) });

  await br.close();
  sec('汇总');
  console.log(`通过 ${P.length} ｜ 失败 ${F.length}`);
  F.forEach(f => console.log('  ❌ ' + f));
  console.log('（本脚本会留下 1 条待办，请自行清理 collab/pending/ ✓）');
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error('E2E 异常：', e); process.exit(2); });
