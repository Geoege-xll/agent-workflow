'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const path = require('node:path').win32;
const cli = require('./bin/agent-workflow.cjs');

function fixture(extra = {}) {
  const cwd = 'C:\\work\\项目 with spaces (a)&';
  const packageRoot = 'C:\\npx cache\\package';
  const stableRoot = 'C:\\Users\\Alice 用户\\AppData\\Local\\AgentWorkflow\\runtimes\\cpython-3.14.10-x64-digest';
  const control = 'C:\\Users\\Alice 用户\\AppData\\Local\\AgentWorkflow\\control\\invocation\\cancel';
  const stable = { python: path.join(stableRoot, 'python.exe'),
    bootstrap: path.join(stableRoot, 'windows_bootstrap.py'), runtime: stableRoot, cancel_file: control };
  const git = 'C:\\Program Files\\Git';
  const files = new Set();
  const directories = new Set([cwd, path.resolve(cwd, '子项目 & special')]);
  const key = (file) => path.normalize(file).toLowerCase();
  const addFile = (file) => files.add(key(file));
  const addGit = (root) => {
    for (const tool of cli.GIT_TOOLS) addFile(path.join(root, 'usr', 'bin', `${tool}.exe`));
    addFile(path.join(root, 'bin', 'bash.exe'));
    addFile(path.join(root, 'cmd', 'git.exe'));
  };
  addGit(git);
  for (const relative of ['runtime/python.exe', 'runtime/manifest.json', 'runtime/windows_bootstrap.py',
    'runtime/windows_fs.py', 'runtime/windows_runtime.py', 'payload/lib/windows_runtime.py', 'payload/lib/install_workflow.py']) {
    addFile(path.join(packageRoot, relative));
  }
  addFile(stable.python);
  addFile(stable.bootstrap);
  const writes = [];
  const calls = [];
  const plans = [];
  const signals = new EventEmitter();
  const output = { stdout: '', stderr: '' };
  const options = {
    cwd, packageRoot, platform: 'win32', arch: 'x64', path,
    env: Object.freeze({ PATH: 'C:\\Windows\\System32', ProgramFiles: 'C:\\Program Files', KEEP: 'unchanged' }),
    fs: {
      statSync(file) {
        const exists = files.has(key(file));
        const directory = [...directories].some((item) => key(item) === key(file));
        if (!exists && !directory) throw Object.assign(new Error('not found'), { code: 'ENOENT' });
        return { isFile: () => exists, isDirectory: () => directory };
      },
      openSync(file, flags, mode) { writes.push(['open', file, flags, mode]); return 99; },
      closeSync(fd) { writes.push(['close', fd]); },
    },
    spawn(executable, args, opts) {
      calls.push({ executable, args, options: opts });
      const plan = plans.shift();
      if (!plan) throw new Error(`Unexpected process: ${executable} ${args.join(' ')}`);
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      child.kill = () => { throw new Error('Never kill a recovering Python process'); };
      setImmediate(() => {
        if (plan.before) plan.before(child);
        if (plan.error) { child.emit('error', new Error(plan.error)); return; }
        for (const chunk of plan.chunks || [Buffer.from(plan.stdout || '')]) child.stdout.emit('data', chunk);
        child.emit('close', plan.code ?? 0, plan.signal || null);
      });
      return child;
    },
    stdout: { write(value) { output.stdout += value; } },
    stderr: { write(value) { output.stderr += value; } }, signals,
    ...extra,
  };
  return { options, stable, control, git, files, directories, addFile, addGit, writes, calls, plans, signals, output,
    deployment: () => ({ stdout: JSON.stringify(stable) }), key };
}

for (const arguments_ of [[], ['--help'], ['-h'], ['init', '--help'], ['init', '-h'], ['--version'], ['-v']]) {
  test(`help/version are read-only on every platform: ${arguments_.join(' ')}`, async () => {
    const f = fixture({ platform: 'darwin', arch: 'arm64', fs: new Proxy({}, { get() { throw new Error('No filesystem access'); } }) });
    assert.equal(await cli.main(arguments_, f.options), 0);
    assert.match(f.output.stdout, arguments_.some((arg) => ['--version', '-v'].includes(arg)) ? /^0\.1\.0\n$/ : /^Usage: agent-workflow/);
    assert.equal(f.calls.length, 0);
    assert.equal(f.signals.listenerCount('SIGINT'), 0);
  });
}

test('strict parser rejects unknown commands/options, duplicates and invalid timeout without writes', async () => {
  for (const arguments_ of [['status'], ['manager'], ['init', 'project'], ['init', '--unknown'], ['--project', 'x'],
    ['init', '--project'], ['init', '--project='], ['init', '--project', '--timeout', '1'],
    ['init', '--project', 'a', '--project', 'b'], ['init', '--help', '--timeout', '1'],
    ...['0', '-1', 'NaN', 'Infinity', '1e999', '', ' ', ' 1', '0x10', '1s', '1\0'].map((value) => ['init', `--timeout=${value}`])]) {
    const f = fixture();
    assert.equal(await cli.main(arguments_, f.options), 2, JSON.stringify(arguments_));
    assert.equal(f.calls.length, 0);
    assert.deepEqual(f.writes, []);
  }
  assert.deepEqual(cli.parseArgs(['init', '--project=foo', '--timeout=.5']), { command: 'init', project: 'foo', timeout: '.5' });
  assert.equal(cli.parseArgs(['init', '--timeout', '1e2']).timeout, '1e2');
});

test('init rejects POSIX and non-x64 without dependency probes or writes', async () => {
  for (const [platform, arch] of [['darwin', 'x64'], ['linux', 'x64'], ['win32', 'arm64'], ['win32', 'ia32']]) {
    const f = fixture({ platform, arch });
    assert.equal(await cli.main(['init'], f.options), 2);
    assert.match(f.output.stderr, /Windows 10\/11 x64 only/);
    assert.equal(f.calls.length, 0);
    assert.deepEqual(f.writes, []);
  }
});

test('missing project or prepared payload is rejected without deployment', async () => {
  for (const missing of ['project', 'runtime/python.exe', 'runtime/manifest.json', 'runtime/windows_fs.py', 'payload/lib/install_workflow.py']) {
    const f = fixture();
    if (missing === 'project') f.directories.clear();
    else f.files.delete(f.key(path.join(f.options.packageRoot, missing)));
    assert.equal(await cli.main(['init'], f.options), 2);
    assert.equal(f.calls.length, 0);
    assert.deepEqual(f.writes, []);
  }
});

test('full Git found outside PATH, child-only environment, absolute original-cwd project and timeout', async () => {
  const f = fixture();
  f.plans.push(f.deployment(), { code: 23 }, {});
  const original = { ...f.options.env };
  assert.equal(await cli.main(['init', '--project', '子项目 & special', '--timeout', '12.5'], f.options), 23);
  assert.equal(f.calls.length, 3);
  const [helper, installer, cleanup] = f.calls;
  assert.equal(helper.executable, path.join(f.options.packageRoot, 'runtime/python.exe'));
  assert.deepEqual(helper.args, [...cli.PYTHON_FLAGS, path.join(f.options.packageRoot, 'payload/lib/windows_runtime.py'),
    '--source', path.join(f.options.packageRoot, 'runtime'), '--manifest', path.join(f.options.packageRoot, 'runtime/manifest.json')]);
  assert.equal(installer.executable, f.stable.python);
  assert.deepEqual(installer.args, [...cli.PYTHON_FLAGS, f.stable.bootstrap, '--script',
    path.join(f.options.packageRoot, 'payload/lib/install_workflow.py'), path.resolve(f.options.cwd, '子项目 & special'), '--timeout', '12.5']);
  assert.equal(installer.options.env.AGENT_WORKFLOW_BASH, path.join(f.git, 'bin/bash.exe'));
  assert.equal(installer.options.env.AGENT_WORKFLOW_PYTHON, f.stable.python);
  assert.equal(installer.options.env.AGENT_WORKFLOW_BOOTSTRAP, f.stable.bootstrap);
  assert.equal(installer.options.env.AGENT_WORKFLOW_CANCEL_FILE, f.control);
  for (const call of f.calls) {
    assert.equal(call.options.shell, false);
    assert.equal(call.options.cwd, f.options.cwd);
    assert.equal(call.options.env.PATH, original.PATH);
    assert.equal(call.options.env.KEEP, 'unchanged');
    assert.equal(call.options.timeout, undefined);
  }
  assert.deepEqual(cleanup.args.slice(-2), ['--cleanup-control', f.control]);
  assert.deepEqual(f.options.env, original);
  assert.deepEqual(f.writes, []);
  assert.equal(f.signals.listenerCount('SIGINT'), 0);
});

test('default project is the invocation cwd, never INIT_CWD or package location', async () => {
  const f = fixture();
  f.options.env = { ...f.options.env, INIT_CWD: 'C:\\not-the-invocation' };
  f.plans.push(f.deployment(), {}, {});
  assert.equal(await cli.main(['init'], f.options), 0);
  assert.equal(f.calls[1].args.at(-1), f.options.cwd);
});

test('stale inherited bootstrap/control paths never reach helper or installer', async () => {
  const f = fixture();
  f.options.env = { ...f.options.env, agent_workflow_bootstrap: 'C:\\old cache\\bootstrap.py',
    AGENT_WORKFLOW_CANCEL_FILE: 'C:\\old cache\\cancel' };
  f.plans.push(f.deployment(), {}, {});
  assert.equal(await cli.main(['init'], f.options), 0);
  assert.equal(f.calls.length, 3);
  assert.equal(f.calls[0].options.env.agent_workflow_bootstrap, undefined);
  assert.equal(f.calls[0].options.env.AGENT_WORKFLOW_CANCEL_FILE, undefined);
  assert.equal(f.calls[1].options.env.AGENT_WORKFLOW_BOOTSTRAP, f.stable.bootstrap);
  assert.equal(f.calls[1].options.env.AGENT_WORKFLOW_CANCEL_FILE, f.control);
  assert.equal(f.options.env.AGENT_WORKFLOW_CANCEL_FILE, 'C:\\old cache\\cancel');
});

test('relative explicit Python is probed once before deployment; bundled interpreter always deploys', async () => {
  const f = fixture();
  f.options.env = { ...f.options.env, agent_workflow_python: 'tools with spaces\\python.exe' };
  const python = path.resolve(f.options.cwd, 'tools with spaces/python.exe');
  f.addFile(python);
  f.plans.push({ stdout: '{"version":[3,11,9]}' }, f.deployment(), {}, {});
  assert.equal(await cli.main(['init'], f.options), 0);
  assert.equal(f.calls.length, 4);
  assert.equal(f.calls[0].executable, python);
  assert.equal(f.calls[0].args[4], '-c');
  assert.equal(f.calls[1].executable, path.join(f.options.packageRoot, 'runtime/python.exe'));
  assert.equal(f.calls[2].executable, python);
  assert.equal(f.calls[2].options.env.AGENT_WORKFLOW_PYTHON, python);
  assert.equal(f.calls[2].options.env.agent_workflow_python, undefined);
  assert.equal(f.calls[2].options.env.AGENT_WORKFLOW_BOOTSTRAP, f.stable.bootstrap);
});

test('invalid explicit Python is fatal, never falls back or deploys; old and malformed probes fail', async () => {
  for (const value of ['', 'missing/python.exe']) {
    const f = fixture();
    f.options.env = { ...f.options.env, AGENT_WORKFLOW_PYTHON: value };
    assert.equal(await cli.main(['init'], f.options), 2);
    assert.equal(f.calls.length, 0);
    assert.deepEqual(f.writes, []);
    assert.match(f.output.stderr, /AGENT_WORKFLOW_PYTHON/);
  }
  for (const plan of [{ stdout: '{"version":[3,10,99]}' }, { stdout: 'Python 3.14' },
    { stdout: '{"version":[3,"14",0]}' }, { stdout: '{"version":[3,14,0]}', code: 1 }, { error: 'cannot execute' }]) {
    const f = fixture();
    f.options.env = { ...f.options.env, AGENT_WORKFLOW_PYTHON: 'python.exe' };
    f.addFile(path.join(f.options.cwd, 'python.exe'));
    f.plans.push(plan);
    assert.equal(await cli.main(['init'], f.options), 2);
    assert.equal(f.calls.length, 1);
    assert.deepEqual(f.writes, []);
  }
});

test('explicit Bash is anchored to invocation cwd and invalid does not fall back to installed Git', async () => {
  const f = fixture();
  const root = path.join(f.options.cwd, 'portable Git');
  f.addGit(root);
  f.options.env = { ...f.options.env, AGENT_WORKFLOW_BASH: 'portable Git/usr/bin/bash.exe' };
  assert.equal(await cli.locateBash(cli.context(f.options), f.options.env), path.join(root, 'usr/bin/bash.exe'));
  for (const value of ['', 'missing/bash.exe', 'C:\\Windows\\System32\\bash.exe']) {
    const invalid = fixture();
    invalid.options.env = { ...invalid.options.env, AGENT_WORKFLOW_BASH: value };
    invalid.addFile('C:\\Windows\\System32\\bash.exe');
    assert.equal(await cli.main(['init'], invalid.options), 2);
    assert.match(invalid.output.stderr, /AGENT_WORKFLOW_BASH/);
    assert.equal(invalid.calls.length, 0);
    assert.deepEqual(invalid.writes, []);
  }
});

test('WSL bash, partial Git and missing usr/bin tools are rejected', async () => {
  const f = fixture();
  f.files.delete(f.key(path.join(f.git, 'usr/bin/cygpath.exe')));
  f.addFile('C:\\Windows\\System32\\bash.exe');
  assert.equal(await cli.main(['init'], f.options), 2);
  assert.match(f.output.stderr, /Full Git for Windows/);
  assert.equal(f.calls.length, 0);
  assert.deepEqual(f.writes, []);
});

test('custom Git cmd PATH and registry installation paths are discovered without PATH mutation', async () => {
  const f = fixture();
  const root = 'D:\\Custom Git';
  f.addGit(root);
  const env = { PATH: `${root}\\cmd;C:\\Windows\\System32` };
  assert.equal(await cli.locateBash(cli.context(f.options), env), path.join(root, 'bin/bash.exe'));
  const registry = 'C:\\Windows\\System32\\reg.exe';
  f.addFile(registry);
  f.plans.push({ code: 1 }, { stdout: `\r\n    InstallPath    REG_SZ    ${root}\r\n` });
  const registryEnv = { PATH: 'C:\\Windows\\System32', SystemRoot: 'C:\\Windows' };
  assert.equal(await cli.locateBash(cli.context(f.options), registryEnv), path.join(root, 'bin/bash.exe'));
  assert.equal(f.calls.length, 2);
  assert.equal(f.calls[0].executable, registry);
  assert.equal(registryEnv.PATH, 'C:\\Windows\\System32');
});

test('deployment errors, malformed JSON and cache-bound runtime fail before installer', async () => {
  for (const plan of [{ code: 7 }, { stdout: 'not JSON' }, { stdout: '{}'}, { stdout: JSON.stringify({
    python: 'C:\\npx cache\\package\\runtime\\python.exe', bootstrap: 'C:\\npx cache\\package\\runtime\\windows_bootstrap.py',
    runtime: 'C:\\npx cache\\package\\runtime' }) }]) {
    const f = fixture();
    f.plans.push(plan);
    assert.equal(await cli.main(['init'], f.options), plan.code || 2);
    assert.equal(f.calls.length, 1);
    assert.deepEqual(f.writes, []);
  }
});

test('helper cancellation channel is mandatory, absolute, named cancel, and outside package cache', async () => {
  for (const value of [undefined, null, 'relative/cancel', 'C:\\control\\wrong-name', 'C:\\npx cache\\package\\control\\cancel',
    'C:\\unrelated cache\\cancel']) {
    const f = fixture();
    f.stable.cancel_file = value;
    f.plans.push(f.deployment());
    assert.equal(await cli.main(['init'], f.options), 2);
    assert.equal(f.calls.length, 1);
    assert.match(f.output.stderr, /private cancellation channel/);
    assert.deepEqual(f.writes, []);
  }
});

test('UTF-8 helper stdout survives chunk boundaries and size is bounded', async () => {
  const f = fixture();
  const json = Buffer.from(JSON.stringify(f.stable));
  f.plans.push({ chunks: [...json].map((byte) => Buffer.from([byte])) }, {}, {});
  assert.equal(await cli.main(['init'], f.options), 0);
  const large = fixture();
  large.plans.push({ stdout: 'x'.repeat(65537) });
  assert.equal(await cli.main(['init'], large.options), 2);
  assert.match(large.output.stderr, /large preflight response/);
});

test('Ctrl+C creates only exclusive helper control file, never kills, waits and cleans through helper', async () => {
  const f = fixture();
  f.plans.push(f.deployment(), { before() { f.signals.emit('SIGINT'); f.signals.emit('SIGINT'); }, code: 130 }, {});
  assert.equal(await cli.main(['init', '--timeout', '0.1'], f.options), 130);
  assert.equal(f.calls.length, 3);
  assert.deepEqual(f.writes, [['open', f.control, 'wx', 0o600], ['close', 99], ['open', f.control, 'wx', 0o600], ['close', 99]]);
  assert.deepEqual(f.calls[2].args.slice(-2), ['--cleanup-control', f.control]);
  assert.match(f.output.stderr, /Waiting for Python cleanup\/recovery/);
  assert.equal(f.signals.listenerCount('SIGINT'), 0);
});

test('cancellation during helper never starts installer and still cleans its control directory', async () => {
  const f = fixture();
  f.plans.push({ ...f.deployment(), before() { f.signals.emit('SIGINT'); } }, {});
  assert.equal(await cli.main(['init'], f.options), 130);
  assert.equal(f.calls.length, 2);
  assert.deepEqual(f.calls[1].args.slice(-2), ['--cleanup-control', f.control]);
  assert.deepEqual(f.writes[0], ['open', f.control, 'wx', 0o600]);
});

test('cleanup failure does not replace installer exit code or trigger unsafe deletion', async () => {
  const f = fixture();
  f.plans.push(f.deployment(), { code: 31 }, { code: 2 });
  assert.equal(await cli.main(['init'], f.options), 31);
  assert.match(f.output.stderr, /control cleanup failed/);
  assert.deepEqual(f.writes, []);
});
