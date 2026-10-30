#!/usr/bin/env node
'use strict';

// One offline entry point, builtins only. Importing this module does not run init.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { StringDecoder } = require('node:string_decoder');
const { version } = require('../package.json');

const HELP = `Usage: agent-workflow [init [--project PATH] [--timeout SECONDS]]
       agent-workflow --help
       agent-workflow --version

init                 Install or safely upgrade the workflow in the current project.
--project PATH       Existing project directory, relative to the invocation directory.
--timeout SECONDS    Finite positive installer timeout; recovery has its own budget.
-h, --help           Show help without checking dependencies or writing files.
-v, --version        Show the local package version.

init requires Windows 10/11 x64, Node.js LTS and full Git for Windows (not WSL).
Python is bundled; init does not download or modify PATH, profiles or policy.
This package is local and unpublished. No manager or TUI is included.
`;
const PYTHON_FLAGS = ['-I', '-B', '-X', 'utf8'];
const GIT_TOOLS = ['bash', 'sh', 'env', 'cygpath', 'awk', 'sed', 'grep', 'find',
  'sort', 'cat', 'cp', 'mv', 'rm', 'mkdir', 'mktemp', 'chmod', 'ln', 'stat',
  'dirname', 'basename', 'cut', 'tr', 'head', 'tail', 'wc', 'date', 'cmp', 'rmdir'];
const OUTPUT_LIMIT = 64 * 1024;

class CliError extends Error {}

function parseArgs(argv) {
  if (!argv.length || (argv.length === 1 && ['-h', '--help'].includes(argv[0]))) return { command: 'help' };
  if (argv.length === 1 && ['-v', '--version'].includes(argv[0])) return { command: 'version' };
  if (argv[0] !== 'init') throw new CliError(`Unknown command: ${argv[0]}. Use --help.`);
  const result = { command: 'init' };
  for (let index = 1; index < argv.length; index += 1) {
    const argument = argv[index];
    if (['-h', '--help'].includes(argument) && argv.length === 2) return { command: 'help' };
    const equal = argument.indexOf('=');
    const flag = equal === -1 ? argument : argument.slice(0, equal);
    if (!['--project', '--timeout'].includes(flag)) throw new CliError(`Unknown option: ${argument}. Use --help.`);
    const key = flag.slice(2);
    if (Object.hasOwn(result, key)) throw new CliError(`Duplicate option: ${flag}`);
    const value = equal === -1 ? argv[++index] : argument.slice(equal + 1);
    if (typeof value !== 'string' || !value.length || value.includes('\0') || value.startsWith('--')) {
      throw new CliError(`${flag} requires a value.`);
    }
    if (key === 'timeout') {
      if (!/^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value)
          || !Number.isFinite(Number(value)) || Number(value) <= 0) {
        throw new CliError('--timeout must be a finite positive number of seconds.');
      }
    }
    result[key] = value;
  }
  return result;
}

function context(options = {}) {
  return {
    cwd: process.cwd(), env: process.env, platform: process.platform, arch: process.arch,
    packageRoot: path.resolve(__dirname, '..'), path, fs, spawn,
    stdout: process.stdout, stderr: process.stderr, signals: process,
    ...options,
  };
}

function environmentValue(env, name) {
  // Windows environment keys are case-insensitive, even in mocked plain objects.
  const key = Object.keys(env).find((candidate) => candidate.toUpperCase() === name.toUpperCase());
  return key === undefined ? undefined : env[key];
}

function childEnvironment(env, additions) {
  const result = { ...env };
  for (const [name, value] of Object.entries(additions)) {
    for (const key of Object.keys(result)) {
      if (key.toUpperCase() === name.toUpperCase()) delete result[key];
    }
    if (value !== undefined) result[name] = value;
  }
  return result;
}

function isFile(ctx, file) {
  try { return ctx.fs.statSync(file).isFile(); } catch { return false; }
}

function within(ctx, root, target) {
  const relative = ctx.path.relative(root, target);
  return !relative || (relative !== '..' && !relative.startsWith(`..${ctx.path.sep}`) && !ctx.path.isAbsolute(relative));
}

function child(ctx, executable, args, env, capture = false, quiet = false) {
  return new Promise((resolve, reject) => {
    let processHandle;
    try {
      processHandle = ctx.spawn(executable, args, {
        cwd: ctx.cwd, env, shell: false, windowsHide: true,
        stdio: capture ? ['inherit', 'pipe', quiet ? 'pipe' : 'inherit'] : 'inherit',
      });
    } catch (error) {
      reject(new CliError(`Cannot start ${executable}: ${error.message}`));
      return;
    }
    let output = '';
    let bytes = 0;
    const decoder = new StringDecoder('utf8');
    if (capture) processHandle.stdout.on('data', (chunk) => {
      bytes += Buffer.byteLength(chunk);
      if (bytes <= OUTPUT_LIMIT) output += decoder.write(Buffer.from(chunk));
    });
    // Drain quiet registry errors rather than leaving a pipe blocked.
    if (quiet && processHandle.stderr) processHandle.stderr.on('data', () => {});
    processHandle.once('error', (error) => reject(new CliError(`Cannot start ${executable}: ${error.message}`)));
    processHandle.once('close', (code, signal) => {
      if (capture) output += decoder.end();
      if (bytes > OUTPUT_LIMIT) {
        reject(new CliError(`Unexpectedly large preflight response from ${executable}.`));
      } else {
        resolve({ code: Number.isInteger(code) ? code : signal === 'SIGINT' ? 130 : signal === 'SIGTERM' ? 143 : 1,
          stdout: output, signal });
      }
    });
    // No Node timer or child.kill: Python owns descendant shutdown and rollback.
  });
}

function gitRoot(ctx, bash) {
  const parent = ctx.path.dirname(bash);
  if (ctx.path.basename(bash).toLowerCase() !== 'bash.exe'
      || ctx.path.basename(parent).toLowerCase() !== 'bin') return null;
  let root = ctx.path.dirname(parent);
  if (ctx.path.basename(root).toLowerCase() === 'usr') root = ctx.path.dirname(root);
  if (!GIT_TOOLS.every((tool) => isFile(ctx, ctx.path.join(root, 'usr', 'bin', `${tool}.exe`)))) return null;
  if (!['cmd', 'bin', 'mingw64/bin'].some((directory) => isFile(ctx, ctx.path.join(root, directory, 'git.exe')))) return null;
  return root;
}

async function locateBash(ctx, env) {
  const explicit = environmentValue(env, 'AGENT_WORKFLOW_BASH');
  if (explicit !== undefined) {
    if (!explicit || explicit.includes('\0')) throw new CliError('AGENT_WORKFLOW_BASH must name Git for Windows bash.exe.');
    const bash = ctx.path.resolve(ctx.cwd, explicit);
    if (!isFile(ctx, bash) || !gitRoot(ctx, bash)) {
      throw new CliError(`AGENT_WORKFLOW_BASH is not a full Git for Windows installation: ${bash}. No fallback was attempted.`);
    }
    return bash;
  }
  const candidates = [];
  const addRoot = (root) => {
    if (root) candidates.push(ctx.path.join(root, 'bin', 'bash.exe'), ctx.path.join(root, 'usr', 'bin', 'bash.exe'));
  };
  for (const name of ['ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)']) {
    const directory = environmentValue(env, name);
    if (directory) addRoot(ctx.path.join(directory, 'Git'));
  }
  const local = environmentValue(env, 'LOCALAPPDATA');
  if (local) addRoot(ctx.path.join(local, 'Programs', 'Git'));
  for (let directory of (environmentValue(env, 'PATH') || '').split(';')) {
    directory = directory.replace(/^"(.*)"$/, '$1');
    if (!directory) continue;
    directory = ctx.path.resolve(ctx.cwd, directory);
    candidates.push(ctx.path.join(directory, 'bash.exe'));
    if (['cmd', 'bin'].includes(ctx.path.basename(directory).toLowerCase())) addRoot(ctx.path.dirname(directory));
  }
  for (const candidate of candidates) {
    if (isFile(ctx, candidate) && gitRoot(ctx, candidate)) return candidate;
  }
  const systemRoot = environmentValue(env, 'SystemRoot');
  const registry = systemRoot && ctx.path.join(systemRoot, 'System32', 'reg.exe');
  if (registry && isFile(ctx, registry)) {
    for (const key of ['HKCU\\SOFTWARE\\GitForWindows', 'HKLM\\SOFTWARE\\GitForWindows', 'HKLM\\SOFTWARE\\WOW6432Node\\GitForWindows']) {
      const result = await child(ctx, registry, ['query', key, '/v', 'InstallPath'], env, true, true);
      if (result.code !== 0) continue;
      const match = result.stdout.match(/^\s*InstallPath\s+REG_SZ\s+(.+?)\s*$/mi);
      if (!match || !ctx.path.isAbsolute(match[1])) continue;
      const bash = ctx.path.join(match[1], 'bin', 'bash.exe');
      if (isFile(ctx, bash) && gitRoot(ctx, bash)) return bash;
    }
  }
  throw new CliError('Full Git for Windows was not found (WSL bash is unsupported). Install Git for Windows, or set AGENT_WORKFLOW_BASH to its bin\\bash.exe. PATH will not be changed.');
}

async function preflight(parsed, ctx) {
  if (ctx.platform !== 'win32' || ctx.arch !== 'x64') throw new CliError('init currently targets Windows 10/11 x64 only. Help and version work on any platform.');
  const project = ctx.path.resolve(ctx.cwd, parsed.project === undefined ? '.' : parsed.project);
  try {
    if (!ctx.fs.statSync(project).isDirectory()) throw new Error('not a directory');
  } catch { throw new CliError(`Project directory does not exist or is not a directory: ${project}`); }
  const bundledPython = ctx.path.join(ctx.packageRoot, 'runtime', 'python.exe');
  const helper = ctx.path.join(ctx.packageRoot, 'payload', 'lib', 'windows_runtime.py');
  const installer = ctx.path.join(ctx.packageRoot, 'payload', 'lib', 'install_workflow.py');
  const runtime = ctx.path.join(ctx.packageRoot, 'runtime');
  const manifest = ctx.path.join(runtime, 'manifest.json');
  for (const file of [bundledPython, helper, installer, manifest,
    ...['windows_bootstrap.py', 'windows_fs.py', 'windows_runtime.py'].map((name) => ctx.path.join(runtime, name))]) {
    if (!isFile(ctx, file)) throw new CliError(`Incomplete offline npm package: missing ${file}. Prepare the package with build_npm_release.py first.`);
  }
  const bash = await locateBash(ctx, ctx.env);
  let env = childEnvironment(ctx.env, { AGENT_WORKFLOW_BASH: bash,
    AGENT_WORKFLOW_BOOTSTRAP: undefined, AGENT_WORKFLOW_CANCEL_FILE: undefined });
  const explicit = environmentValue(ctx.env, 'AGENT_WORKFLOW_PYTHON');
  let selectedPython;
  if (explicit !== undefined) {
    if (!explicit || explicit.includes('\0')) throw new CliError('AGENT_WORKFLOW_PYTHON must name Python >= 3.11; an invalid explicit selection never falls back.');
    selectedPython = ctx.path.resolve(ctx.cwd, explicit);
    if (!isFile(ctx, selectedPython)) throw new CliError(`AGENT_WORKFLOW_PYTHON must name Python >= 3.11: ${selectedPython}. No fallback was attempted.`);
    const probe = await child(ctx, selectedPython, [...PYTHON_FLAGS, '-c',
      'import json,sys; print(json.dumps({"version": list(sys.version_info[:3])}))'], env, true);
    let info;
    try { info = JSON.parse(probe.stdout); } catch { /* Report the explicit selection, never silently replace it. */ }
    if (probe.code !== 0 || !info || !Array.isArray(info.version) || info.version.length !== 3
        || !info.version.every(Number.isInteger) || info.version[0] < 3
        || (info.version[0] === 3 && info.version[1] < 11)) {
      throw new CliError(`AGENT_WORKFLOW_PYTHON must be Python >= 3.11: ${selectedPython}. No fallback was attempted.`);
    }
    env = childEnvironment(env, { AGENT_WORKFLOW_PYTHON: selectedPython });
  }
  return { project, bundledPython, helper, installer, runtime, manifest, selectedPython, env };
}

function cancellation(ctx) {
  const state = { signal: null, file: null };
  const notify = () => {
    if (!state.file) return;
    try {
      const descriptor = ctx.fs.openSync(state.file, 'wx', 0o600);
      ctx.fs.closeSync(descriptor);
    } catch (error) {
      if (error.code !== 'EEXIST') ctx.stderr.write(`Cannot send safe cancellation request: ${error.message}. Waiting for the installer; it will not be killed.\n`);
    }
  };
  const handlers = new Map(['SIGINT', 'SIGTERM'].map((signal) => [signal, () => {
    if (!state.signal) ctx.stderr.write('Cancellation requested. Waiting for Python cleanup/recovery; do not close this terminal.\n');
    state.signal ||= signal;
    notify();
  }]));
  for (const [signal, handler] of handlers) ctx.signals.on(signal, handler);
  return {
    state,
    setFile(file) { state.file = file; if (state.signal) notify(); },
    dispose() { for (const [signal, handler] of handlers) ctx.signals.removeListener(signal, handler); },
    exitCode() { return state.signal === 'SIGTERM' ? 143 : 130; },
  };
}

async function initialize(parsed, ctx) {
  const cancel = cancellation(ctx);
  let checked;
  let controlFile;
  try {
    checked = await preflight(parsed, ctx);
    if (cancel.state.signal) return cancel.exitCode();
    const deployed = await child(ctx, checked.bundledPython, [...PYTHON_FLAGS, checked.helper,
      '--source', checked.runtime, '--manifest', checked.manifest], checked.env, true);
    if (deployed.code !== 0) return deployed.code;
    let stable;
    try { stable = JSON.parse(deployed.stdout); } catch { throw new CliError('Runtime deployment helper returned invalid JSON.'); }
    if (!stable || !['python', 'bootstrap', 'runtime', 'cancel_file'].every((name) => typeof stable[name] === 'string'
      && !stable[name].includes('\0') && ctx.path.isAbsolute(stable[name]))
        || !isFile(ctx, stable.python) || !isFile(ctx, stable.bootstrap)
        || ctx.path.dirname(stable.python).toLowerCase() !== stable.runtime.toLowerCase()
        || ctx.path.dirname(stable.bootstrap).toLowerCase() !== stable.runtime.toLowerCase()
        || ctx.path.basename(stable.python).toLowerCase() !== 'python.exe'
        || ctx.path.basename(stable.bootstrap).toLowerCase() !== 'windows_bootstrap.py'
        || ctx.path.basename(stable.cancel_file) !== 'cancel'
        || within(ctx, ctx.packageRoot, stable.runtime)
        || within(ctx, ctx.packageRoot, stable.cancel_file)
        || !within(ctx, ctx.path.join(ctx.path.dirname(ctx.path.dirname(stable.runtime)), 'control'), stable.cancel_file)) {
      throw new CliError('Runtime deployment helper did not return valid persistent interpreter/bootstrap paths and a private cancellation channel.');
    }
    controlFile = stable.cancel_file;
    cancel.setFile(controlFile);
    if (cancel.state.signal) return cancel.exitCode();
    const python = checked.selectedPython || stable.python;
    const additions = { AGENT_WORKFLOW_PYTHON: python, AGENT_WORKFLOW_BOOTSTRAP: stable.bootstrap };
    if (controlFile) additions.AGENT_WORKFLOW_CANCEL_FILE = controlFile;
    const env = childEnvironment(checked.env, additions);
    const args = [...PYTHON_FLAGS, stable.bootstrap, '--script', checked.installer, checked.project];
    if (parsed.timeout !== undefined) args.push('--timeout', parsed.timeout);
    const result = await child(ctx, python, args, env);
    return result.code || (cancel.state.signal ? cancel.exitCode() : 0);
  } finally {
    // Only the trusted helper removes its private control directory. Never rm -r a returned path.
    if (controlFile && checked) {
      try {
        const result = await child(ctx, checked.bundledPython,
          [...PYTHON_FLAGS, checked.helper, '--cleanup-control', controlFile], checked.env);
        if (result.code !== 0) ctx.stderr.write('Warning: runtime cancellation control cleanup failed; no other directories were removed.\n');
      } catch (error) { ctx.stderr.write(`Warning: ${error.message}\n`); }
    }
    cancel.dispose();
  }
}

async function main(argv = process.argv.slice(2), options = {}) {
  const ctx = context(options);
  try {
    const parsed = parseArgs(argv);
    if (parsed.command === 'help') { ctx.stdout.write(HELP); return 0; }
    if (parsed.command === 'version') { ctx.stdout.write(`${version}\n`); return 0; }
    return await initialize(parsed, ctx);
  } catch (error) {
    ctx.stderr.write(`[ERROR] ${error.message}\n`);
    return 2;
  }
}

module.exports = { HELP, PYTHON_FLAGS, GIT_TOOLS, CliError, parseArgs, context,
  childEnvironment, locateBash, preflight, main };
if (require.main === module) main().then((code) => { process.exitCode = code; });
