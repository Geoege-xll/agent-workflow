from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


PACK = Path(__file__).resolve().parents[1]
TEMPLATES = PACK / "templates/prototype"


class TemplateTree(HTMLParser):
    """只把真实模板转换成测试 DOM 输入，不重写工作区的登记或路由算法。"""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "document", "attrs": {}, "children": []}
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        self.stack[-1]["children"].append(text)


# 这里仅提供真实脚本需要的 DOM/事件最小接口。原生 details 的 open/toggle 由用例
# 显式触发；它不是浏览器布局、键盘实操、辅助技术或跨 file 安全策略的模拟认证。
NODE_DOM = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }
  fire(type, event = {}) { for (const handler of this.listeners.get(type) || []) handler(event); }
}
function matches(node, selector) {
  const m = selector.trim().match(/^([a-z0-9-]+)?(?:#([a-z0-9-]+))?(?:\.([a-z0-9-]+))?(?:\[([a-z0-9-]+)(?:="([^"]*)")?\])?$/i);
  assert.ok(m, `测试 DOM 未支持的选择器：${selector}`);
  return (!m[1] || node.tagName === m[1].toUpperCase()) && (!m[2] || node.getAttribute('id') === m[2])
    && (!m[3] || node.classList.contains(m[3])) && (!m[4] || node.hasAttribute(m[4]))
    && (m[5] === undefined || node.getAttribute(m[4]) === m[5]);
}
class Element extends Events {
  constructor(tag, attrs = {}, owner) {
    super(); this.tagName = tag.toUpperCase(); this.attrs = {...attrs}; this.childNodes = [];
    this.parentElement = null; this.ownerDocument = owner; this.srcWrites = [];
    const self = this;
    this.classList = {
      contains(value) { return (self.attrs.class || '').split(/\s+/).includes(value); },
      add(value) { if (!this.contains(value)) self.attrs.class = `${self.attrs.class || ''} ${value}`.trim(); },
      toggle(value, force) {
        const enabled = force === undefined ? !this.contains(value) : force;
        if (enabled) this.add(value);
        else self.attrs.class = (self.attrs.class || '').split(/\s+/).filter(item => item !== value).join(' ');
        return enabled;
      }
    };
    if (this.tagName === 'IFRAME') {
      this.contentWindow = {messages: [], postMessage(data, origin) { this.messages.push({data, origin}); }};
      // 真实控制器一旦越过消息边界访问跨文档 DOM，夹具立即失败。
      Object.defineProperty(this, 'contentDocument', {get() { throw Error('禁止跨文档 DOM'); }});
      for (const key of ['document', 'location']) Object.defineProperty(this.contentWindow, key, {get() { throw Error('禁止跨文档读取'); }});
    }
  }
  get children() { return this.childNodes.filter(item => typeof item !== 'string'); }
  get hidden() { return this.hasAttribute('hidden'); }
  set hidden(value) { value ? this.setAttribute('hidden', '') : this.removeAttribute('hidden'); }
  get open() { return this.hasAttribute('open'); }
  set open(value) { value ? this.setAttribute('open', '') : this.removeAttribute('open'); }
  get textContent() { return this.childNodes.map(item => typeof item === 'string' ? item : item.textContent).join(''); }
  set textContent(value) { this.childNodes = [String(value)]; }
  getAttribute(name) { return this.hasAttribute(name) ? (this.attrs[name] ?? '') : null; }
  hasAttribute(name) { return Object.hasOwn(this.attrs, name); }
  setAttribute(name, value) { this.attrs[name] = String(value); if (name === 'src') this.srcWrites.push(String(value)); }
  removeAttribute(name) { delete this.attrs[name]; }
  append(...nodes) { for (const node of nodes) { this.childNodes.push(node); if (typeof node !== 'string') node.parentElement = this; } }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  querySelectorAll(selector) {
    const selectors = selector.split(','); const found = [];
    for (const child of this.children) {
      if (selectors.some(item => matches(child, item))) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { for (let node = this; node; node = node.parentElement) if (matches(node, selector)) return node; return null; }
  focus() { this.ownerDocument.activeElement = this; }
  scrollIntoView(options) { this.lastScroll = options; }
}
function environment(tree, href, embedded = false) {
  const document = new Element('document'); document.ownerDocument = document;
  document.createElement = tag => new Element(tag, {}, document);
  function build(spec) {
    if (typeof spec === 'string') return spec;
    const node = new Element(spec.tag, spec.attrs, document);
    node.append(...spec.children.map(build)); return node;
  }
  document.append(...tree.children.map(build));
  document.getElementById = id => document.querySelector(`#${id}`);
  document.body = document.querySelector('body'); document.activeElement = document.body;
  const window = new Events(); window.location = new URL(href); window.crypto = webcrypto;
  window.parent = embedded ? {messages: [], postMessage(data, origin) { this.messages.push({data, origin}); }} : window;
  window.history = {replaceState(_state, _title, url) { window.location = new URL(url); }};
  const context = vm.createContext({window, document, URL, Uint8Array, console,
    fetch() { throw Error('禁止网络访问'); }, XMLHttpRequest: class { constructor() { throw Error('禁止网络访问'); } }});
  return {window, document, frame: document.getElementById('prototype-preview'), run(source) { vm.runInContext(source, context); }};
}
function node(env, tag, attrs = {}, children = []) {
  const element = env.document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  element.append(...children); return element;
}
function index(href = 'file:///offline/prototype/index.html', names = ['settings.html', 'reports.html', 'guide.html']) {
  const env = environment(fixture.index, href); const nav = env.document.getElementById('prototype-pages');
  const groups = [node(env, 'details', {id: 'group-main'}, [node(env, 'summary', {}, ['主要页面'])]),
    node(env, 'details', {id: 'group-more'}, [node(env, 'summary', {}, ['其他页面'])])];
  const links = names.map((name, i) => node(env, 'a', {href: name}, [`页面 ${i + 1}`]));
  links.forEach((link, i) => groups[i < 2 ? 0 : 1].append(link)); nav.append(...groups);
  env.links = links; env.groups = groups; return env;
}
function click(target, extra = {}) {
  const event = {target, button: 0, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra};
  for (let node = target; node; node = node.parentElement) node.fire('click', event);
  return event;
}
function load(env) { env.frame.fire('load'); return env.frame.contentWindow.messages.findLast(item => item.data.type === 'prototype-workspace:connect').data; }
function intent(env, connection, patch = {}, eventPatch = {}) {
  env.window.fire('message', {source: env.frame.contentWindow, origin: env.window.location.protocol === 'file:' ? 'null' : env.window.location.origin,
    data: {...connection, type: 'prototype-workspace:intent', intent: 'reveal-navigation', ...patch}, ...eventPatch});
}
const chosen = env => env.links.filter(link => link.getAttribute('aria-current') === 'page');
"""


SCENARIOS = {
    "navigation": r"""
const env = index('file:///offline/prototype/index.html#page=reports.html'); env.run(fixture.workspace);
assert.deepEqual(env.frame.srcWrites, ['reports.html']); assert.equal(chosen(env)[0], env.links[1]);
assert.equal(env.document.getElementById('prototype-page-count').textContent, '3 页');
assert.equal(env.groups[0].open, true); assert.equal(env.groups[1].open, false);
env.groups[0].open = false; env.groups[0].fire('toggle');
assert.equal(env.groups[0].children[0].getAttribute('aria-expanded'), 'false');
assert.deepEqual(env.frame.srcWrites, ['reports.html']);
assert.equal(click(env.links[2]).defaultPrevented, true); assert.equal(chosen(env).length, 1);
assert.equal(chosen(env)[0], env.links[2]); assert.equal(env.window.location.hash, '#page=guide.html');
assert.equal(env.groups[1].open, true); assert.equal(env.frame.getAttribute('aria-busy'), 'true');
const connection = load(env); assert.equal(env.frame.getAttribute('aria-busy'), 'false');
assert.equal(env.document.activeElement, env.frame); assert.equal(connection.focusHeading, true);
click(env.document.getElementById('prototype-sidebar-toggle')); assert.equal(env.document.getElementById('prototype-sidebar').hidden, true);
env.groups[1].open = false; env.groups[1].fire('toggle'); intent(env, connection);
assert.equal(env.document.getElementById('prototype-sidebar').hidden, false);
assert.equal(env.groups[1].open, true); assert.equal(env.document.activeElement, env.links[2]);
assert.equal(env.links[2].lastScroll.block, 'nearest');
const before = env.frame.srcWrites.length; click(env.links[2]); assert.equal(env.frame.srcWrites.length, before);
assert.equal(click(env.links[0], {ctrlKey: true}).defaultPrevented, false);
env.window.location.hash = '#page=settings.html'; env.window.fire('hashchange');
assert.equal(env.frame.getAttribute('src'), 'settings.html'); assert.equal(chosen(env)[0], env.links[0]);
env.window.location.hash = '#page=guide.html'; env.window.fire('hashchange'); assert.equal(chosen(env)[0], env.links[2]);
assert.equal(env.document.querySelectorAll('iframe').length, 1);
assert.equal(env.document.querySelectorAll('[data-prototype-current-marker]').filter(item => !item.hidden).length, 1);
console.log('真实控制器：单页按需加载、唯一选中、深链/历史、原生分组、侧栏与返回焦点通过');
""",
    "security": r"""
for (const hash of ['#page=../../secret.html', '#page=https%3A%2F%2Fexample.test%2Fa.html', '#page=missing.html', '#page=index.html', '#page=%', '#page=%252e%252e%252fsecret.html', '#other']) {
  const env = index(`file:///offline/prototype/index.html${hash}`); env.run(fixture.workspace);
  assert.deepEqual(env.frame.srcWrites, ['settings.html']); assert.equal(env.window.location.hash, '#page=settings.html');
}
const env = index(); env.run(fixture.workspace); let connection = load(env);
const toggle = env.document.getElementById('prototype-sidebar-toggle'); click(toggle);
for (const [patch, event] of [ [{token: '0'.repeat(32)}, {}], [{page: 'reports.html'}, {}], [{version: 2}, {}],
  [{type: 'unknown'}, {}], [{intent: 'execute'}, {}], [{}, {source: {}}], [{}, {origin: 'https://example.test'}] ]) {
  intent(env, connection, patch, event); assert.equal(env.document.getElementById('prototype-sidebar').hidden, true);
}
for (const target of ['../secret.html', 'https://example.test/a.html', 'index.html', 'missing.html', './reports.html', 'reports.html#state']) {
  intent(env, connection, {intent: 'navigate', target}); assert.deepEqual(env.frame.srcWrites, ['settings.html']);
}
intent(env, connection, {intent: 'navigate', target: 'reports.html'}); assert.equal(env.frame.getAttribute('src'), 'reports.html');
// 原 WindowProxy 在导航后可以保持不变；旧页/旧会话均不能驱动新的选择或侧栏。
intent(env, connection); assert.equal(env.document.getElementById('prototype-sidebar').hidden, true);
const next = load(env); assert.notEqual(next.token, connection.token);
intent(env, next, {token: connection.token}); assert.equal(env.document.getElementById('prototype-sidebar').hidden, true);
intent(env, next); assert.equal(env.document.getElementById('prototype-sidebar').hidden, false);
const http = index('https://local.test/prototype/index.html'); http.run(fixture.workspace); connection = load(http);
assert.equal(http.frame.contentWindow.messages[0].origin, 'https://local.test'); click(http.document.getElementById('prototype-sidebar-toggle'));
intent(http, connection, {}, {origin: 'null'}); assert.equal(http.document.getElementById('prototype-sidebar').hidden, true);
intent(http, connection); assert.equal(http.document.getElementById('prototype-sidebar').hidden, false);
console.log('真实控制器：未知/越界/编码 hash、来源/页名/会话/意图拒绝、导航后陈旧消息和 HTTP origin 通过');
""",
    "empty_and_structure": r"""
const empty = index(undefined, []); empty.run(fixture.workspace);
assert.equal(empty.frame.hasAttribute('src'), false); assert.equal(empty.frame.hidden, true); assert.equal(empty.frame.srcWrites.length, 0);
for (const names of [['../bad.html'], ['https://example.test/a.html'], ['index.html'], ['a.html', 'a.html'], ['UPPER.html'], ['%61.html']]) {
  const env = index(undefined, names); env.run(fixture.workspace); assert.equal(env.frame.srcWrites.length, 0);
  assert.equal(env.frame.hidden, true); assert.equal(click(env.links[0], {ctrlKey: true}).defaultPrevented, true);
}
const nested = index(); nested.window.parent = {}; nested.run(fixture.workspace); assert.equal(nested.frame.srcWrites.length, 0);
const extra = index(); extra.document.body.append(node(extra, 'iframe')); extra.run(fixture.workspace); assert.equal(extra.frame.srcWrites.length, 0);
const inline = index(); inline.frame.setAttribute('srcdoc', 'untrusted'); inline.run(fixture.workspace);
assert.equal(inline.frame.hasAttribute('srcdoc'), false); assert.equal(inline.frame.hasAttribute('src'), false);
console.log('真实控制器：空登记无加载、非法/重复登记、额外 frame、srcdoc 和嵌套 index 拒绝通过');
""",
    "page_bridge": r"""
const direct = environment(fixture.page, 'file:///offline/prototype/settings.html'); direct.run(fixture.shell);
assert.equal(direct.document.getElementById('prototype-back-index').getAttribute('href'), 'index.html#page=settings.html');
assert.equal(direct.document.getElementById('prototype-page-sidebar-toggle').hidden, true);
const parent = index(); parent.run(fixture.workspace);
function attach(name) {
  const child = environment(fixture.page, `file:///offline/prototype/${name}`, true);
  const parentProxy = {postMessage(data) { parent.window.fire('message', {source: childProxy, origin: 'null', data}); }};
  const childProxy = {postMessage(data) { child.window.fire('message', {source: parentProxy, origin: 'null', data}); }};
  child.window.parent = parentProxy; parent.frame.contentWindow = childProxy; child.run(fixture.shell); return child;
}
const child = attach('settings.html'); const pageToggle = child.document.getElementById('prototype-page-sidebar-toggle');
// 未认证和错误上下文都不显示开关。
const forged = {type: 'prototype-workspace:connect', version: 1, page: 'settings.html', token: 'a'.repeat(32), sidebarExpanded: true};
for (const event of [{source: {}, origin: 'null', data: forged}, {source: child.window.parent, origin: 'https://example.test', data: forged},
  {source: child.window.parent, origin: 'null', data: {...forged, page: 'other.html'}},
  {source: child.window.parent, origin: 'null', data: {...forged, token: 'bad'}}]) child.window.fire('message', event);
assert.equal(pageToggle.hidden, true); parent.frame.fire('load');
assert.equal(pageToggle.hidden, false); assert.equal(parent.document.getElementById('prototype-sidebar-toggle').hidden, true);
click(pageToggle); assert.equal(parent.document.getElementById('prototype-sidebar').hidden, true);
assert.equal(pageToggle.getAttribute('aria-expanded'), 'false');
// 父级的正确窗口也不能用旧 token 覆盖页头状态。
child.window.fire('message', {source: child.window.parent, origin: 'null', data: {...forged, type: 'prototype-workspace:state'}});
assert.equal(pageToggle.getAttribute('aria-expanded'), 'false');
const back = child.document.getElementById('prototype-back-index'); assert.equal(click(back).defaultPrevented, true);
assert.equal(parent.document.getElementById('prototype-sidebar').hidden, false);
assert.equal(pageToggle.getAttribute('aria-expanded'), 'true'); assert.equal(parent.document.activeElement, parent.links[0]);
const content = child.document.querySelector('main[data-prototype-page-content]');
const local = node(child, 'a', {href: 'reports.html'}, ['下页']); content.append(local); click(local);
assert.equal(parent.frame.getAttribute('src'), 'reports.html');
// 切换后旧页开关仍有旧会话，但不能更改父级当前状态。
click(pageToggle); assert.equal(parent.document.getElementById('prototype-sidebar').hidden, false);
assert.equal(parent.document.getElementById('prototype-sidebar-toggle').hidden, false);
const next = attach('reports.html'); parent.frame.fire('load');
assert.equal(next.document.getElementById('prototype-page-sidebar-toggle').hidden, false);
assert.equal(next.document.activeElement, next.document.getElementById('prototype-page-title'));
assert.equal(parent.document.getElementById('prototype-sidebar-toggle').hidden, true);
for (const href of ['../secret.html', 'https://example.test/a.html', 'javascript:alert(1)', './settings.html']) {
  const link = node(next, 'a', {href}, ['拒绝']); next.document.body.append(link); assert.equal(click(link).defaultPrevented, true);
  assert.equal(parent.frame.getAttribute('src'), 'reports.html');
}
const state = node(next, 'a', {href: '#details'}, ['本页状态']); next.document.body.append(state); assert.equal(click(state).defaultPrevented, false);
const documents = next.document.querySelector('nav.prototype-requirement-links');
const requirement = node(next, 'a', {href: '../../plans/topic.html', 'data-prototype-document': 'html', target: '_blank', rel: 'noopener'}, ['需求']);
documents.append(requirement); assert.equal(click(requirement).defaultPrevented, false);
assert.equal(parent.frame.getAttribute('src'), 'reports.html');
console.log('真实双控制器：独立页深链、认证前隐藏、唯一开关、父级 expanded 同步、返回焦点、切换旧消息拒绝及文档独立导航通过');
""",
}


class PrototypeWorkspaceRuntimeTest(unittest.TestCase):
    def run_node(self, scenario: str) -> None:
        self.assertIsNotNone(shutil.which("node"), "真实控制器验证必须提供 Node，不能以跳过替代成功")
        sources = {name: (TEMPLATES / name).read_text(encoding="utf-8") for name in ("index.html", "page.html", "workspace.js", "page-shell.js")}
        payload = {"index": TemplateTree(sources["index.html"]).root, "page": TemplateTree(sources["page.html"]).root,
                   "workspace": sources["workspace.js"], "shell": sources["page-shell.js"]}
        script = "const fixture = " + json.dumps(payload, ensure_ascii=False) + ";\n" + NODE_DOM + SCENARIOS[scenario]
        result = subprocess.run(["node", "-"], input=script, text=True, capture_output=True, cwd=PACK, timeout=20)
        # 完整节点输出与确切输入 SHA 随 unittest 日志保留；不建立预览树或额外依赖缓存。
        print(json.dumps({"scenario": scenario, "argv": ["node", "-"], "cwd": str(PACK), "env_overrides": {},
                          "stdin_sha256": hashlib.sha256(script.encode()).hexdigest(),
                          "source_sha256": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in sources.items()},
                          "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}, ensure_ascii=False))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_real_controller_navigation_and_focus(self):
        self.run_node("navigation")

    def test_real_controller_hash_and_message_boundary(self):
        self.run_node("security")

    def test_real_controller_empty_and_structural_rejection(self):
        self.run_node("empty_and_structure")

    def test_real_page_shell_and_workspace_state_bridge(self):
        self.run_node("page_bridge")


if __name__ == "__main__":
    unittest.main()
