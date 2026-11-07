'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const path = require('node:path');
const { runtimeSelection, main } = require('../lib/python_runtime.cjs');

function fixture(body = 'C:\\stable runtime\\python.exe\nC:\\stable runtime\\windows_bootstrap.py\n') {
  const root = path.resolve('/project/.agent-workflow');
  const record = path.join(root, 'lib', 'windows-runtime.paths');
  const seen = [];
  const fs = {
    lstatSync(file) {
      seen.push(file);
      return { isFile: () => true, isSymbolicLink: () => false, nlink: 1,
        size: file === record ? Buffer.byteLength(body) : 10 };
    },
    readFileSync(file) { assert.equal(file, record); return Buffer.from(body); },
  };
  return { root, fs, seen, cwd: 'D:\\caller 项目', env: {}, platform: 'win32' };
}

test('stable selection is project-local and never consults PATH or npm cache', () => {
  const ctx = fixture();
  const env = { Path: 'user path', PYTHONPATH: 'untrusted' };
  assert.deepEqual(runtimeSelection(ctx.root, env, ctx.cwd, ctx.fs), {
    python: 'C:\\stable runtime\\python.exe', bootstrap: 'C:\\stable runtime\\windows_bootstrap.py',
  });
  assert.deepEqual(env, { Path: 'user path', PYTHONPATH: 'untrusted' });
});

test('explicit relative Python is cwd-anchored, case-insensitive and never falls back', () => {
  const ctx = fixture();
  assert.equal(runtimeSelection(ctx.root, { agent_workflow_python: '.\\custom.exe' },
    ctx.cwd, ctx.fs).python, 'D:\\caller 项目\\custom.exe');
  for (const value of ['', '\0', '\n']) {
    assert.throws(() => runtimeSelection(ctx.root, { AGENT_WORKFLOW_PYTHON: value }, ctx.cwd, ctx.fs));
  }
  assert.throws(() => runtimeSelection(ctx.root, { AGENT_WORKFLOW_BOOTSTRAP: '' }, ctx.cwd, ctx.fs));
  ctx.fs.lstatSync = (file) => { throw new Error(`missing: ${file}`); };
  assert.throws(() => runtimeSelection(ctx.root, { AGENT_WORKFLOW_PYTHON: 'missing.exe' }, ctx.cwd, ctx.fs));
});

test('malformed, cache-bound, nonlocal and extra-line records fail closed', () => {
  const valid = 'C:\\runtime\\python.exe\nC:\\runtime\\windows_bootstrap.py\n';
  for (const body of [valid + 'extra', valid + '\n', valid.replace(/\n/g, '\r\n'),
    valid.trimEnd(), valid.replace('C:\\runtime\\python.exe', 'relative.exe'),
    valid.replace('C:\\runtime\\python.exe', '\\\\server\\share\\python.exe'),
    valid.replace('C:\\runtime\\python.exe', 'C:\\npm\\_npx\\python.exe')]) {
    const ctx = fixture(body);
    assert.throws(() => runtimeSelection(ctx.root, ctx.env, ctx.cwd, ctx.fs));
  }
  const ctx = fixture();
  ctx.fs.readFileSync = () => Buffer.from([0xff, 0xfe]);
  assert.throws(() => runtimeSelection(ctx.root, ctx.env, ctx.cwd, ctx.fs));
});

test('linked, oversized and missing records are rejected', () => {
  for (const replacement of [{ nlink: 2 }, { size: 65537 }, { isFile: () => false },
    { isSymbolicLink: () => true }]) {
    const ctx = fixture();
    const original = ctx.fs.lstatSync;
    ctx.fs.lstatSync = (file) => ({ ...original(file), ...replacement });
    assert.throws(() => runtimeSelection(ctx.root, ctx.env, ctx.cwd, ctx.fs));
  }
});

test('native invocation preserves Unicode argv, stdin/stdout/stderr, cwd and exit status', async () => {
  const ctx = fixture();
  ctx.env = { Path: 'caller path', agent_workflow_project_runtime: 'untrusted' };
  const before = { ...ctx.env };
  const args = ['-X', 'utf8', 'D:\\caller 项目\\.agent-workflow\\lib\\task_graph_cli.py', 'ready',
    '--input', 'snapshot & 中文.json'];
  ctx.spawn = (executable, argv, options) => {
    assert.equal(executable, 'C:\\stable runtime\\python.exe');
    assert.deepEqual(argv, ['-I', '-B', '-X', 'utf8', 'C:\\stable runtime\\windows_bootstrap.py',
      '--script', ...args]);
    assert.equal(options.shell, false);
    assert.equal(options.stdio, 'inherit');
    assert.equal(options.cwd, ctx.cwd);
    assert.equal(options.env.Path, 'caller path');
    assert.equal(options.env.AGENT_WORKFLOW_PROJECT_RUNTIME, ctx.root);
    assert.equal(options.env.AGENT_WORKFLOW_PYTHON, executable);
    assert.equal(options.env.AGENT_WORKFLOW_BOOTSTRAP, argv[4]);
    assert.equal(options.env.agent_workflow_project_runtime, undefined);
    const child = new EventEmitter();
    queueMicrotask(() => child.emit('close', 23, null));
    return child;
  };
  assert.equal(await main(args, ctx), 23);
  assert.deepEqual(ctx.env, before);
});

test('non-Windows and spawn failures are controlled and do not try a fallback', async () => {
  const messages = [];
  const ctx = fixture();
  ctx.stderr = { write: (message) => messages.push(message) };
  ctx.platform = 'darwin';
  ctx.fs = { lstatSync: () => assert.fail('must not inspect runtime') };
  assert.equal(await main([], ctx), 2);
  assert.match(messages.pop(), /python_runtime.sh/);
  Object.assign(ctx, fixture());
  let calls = 0;
  ctx.spawn = () => {
    calls += 1;
    const child = new EventEmitter();
    queueMicrotask(() => child.emit('error', new Error('not executable')));
    return child;
  };
  assert.equal(await main(['-c', 'print(1)'], ctx), 2);
  assert.equal(calls, 1);
  assert.match(messages.pop(), /not executable/);
});
