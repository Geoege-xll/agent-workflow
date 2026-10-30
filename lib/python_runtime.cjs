#!/usr/bin/env node
'use strict';

// Project-local Windows helper. No manager, global registration or PATH edits.
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { TextDecoder } = require('node:util');

function environmentValue(env, name) {
  const key = Object.keys(env).find((item) => item.toUpperCase() === name);
  return key === undefined ? undefined : env[key];
}

function localPath(value) {
  return typeof value === 'string' && /^[a-z]:[\\/]/i.test(value)
    && !/[\r\n\0]/.test(value) && path.win32.isAbsolute(value)
    && !value.split(/[\\/]/).some((part) => ['_npx', '_cacache'].includes(part.toLowerCase()));
}

function runtimeSelection(root, env, cwd, filesystem = fs) {
  const record = path.join(root, 'lib', 'windows-runtime.paths');
  const info = filesystem.lstatSync(record);
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size > 65536) {
    throw new Error('Expected a single-link persistent runtime record; reinstall with npx init.');
  }
  const body = new TextDecoder('utf-8', { fatal: true }).decode(filesystem.readFileSync(record));
  const lines = body.split('\n');
  if (lines.length !== 3 || lines[2] !== '' || !lines.slice(0, 2).every(localPath)) {
    throw new Error('Invalid persistent Windows runtime record; reinstall with npx init.');
  }
  const explicitPython = environmentValue(env, 'AGENT_WORKFLOW_PYTHON');
  const explicitBootstrap = environmentValue(env, 'AGENT_WORKFLOW_BOOTSTRAP');
  if (explicitPython !== undefined && (typeof explicitPython !== 'string'
      || !explicitPython || /[\r\n\0]/.test(explicitPython))) {
    throw new Error('Explicit AGENT_WORKFLOW_PYTHON must name an executable.');
  }
  const python = explicitPython === undefined ? lines[0] : path.win32.resolve(cwd, explicitPython);
  const bootstrap = explicitBootstrap === undefined ? lines[1] : explicitBootstrap;
  if (!localPath(python) || !localPath(bootstrap)
      || path.win32.basename(bootstrap).toLowerCase() !== 'windows_bootstrap.py') {
    throw new Error('A local absolute Python and stable windows_bootstrap.py are required.');
  }
  for (const file of [python, bootstrap]) {
    const entry = filesystem.lstatSync(file);
    if (!entry.isFile() || entry.isSymbolicLink() || entry.nlink !== 1) {
      throw new Error(`Persistent runtime file is missing or unsafe: ${file}`);
    }
  }
  return { python, bootstrap };
}

async function main(arguments_, options = {}) {
  const ctx = {
    platform: process.platform, env: process.env, cwd: process.cwd(),
    root: path.resolve(__dirname, '..'), fs, spawn, stderr: process.stderr,
    ...options,
  };
  try {
    if (ctx.platform !== 'win32') throw new Error('Use lib/python_runtime.sh on macOS/Linux.');
    const { python, bootstrap } = runtimeSelection(ctx.root, ctx.env, ctx.cwd, ctx.fs);
    const env = { ...ctx.env };
    for (const key of Object.keys(env)) {
      if (['AGENT_WORKFLOW_PROJECT_RUNTIME', 'AGENT_WORKFLOW_PYTHON', 'AGENT_WORKFLOW_BOOTSTRAP']
        .includes(key.toUpperCase())) delete env[key];
    }
    env.AGENT_WORKFLOW_PROJECT_RUNTIME = ctx.root;
    env.AGENT_WORKFLOW_PYTHON = python;
    env.AGENT_WORKFLOW_BOOTSTRAP = bootstrap;
    // The trusted bootstrap supplies explicit script/module imports under -I;
    // neither the caller cwd nor npx's package directory is an import root.
    return await new Promise((resolve, reject) => {
      const child = ctx.spawn(python, ['-I', '-B', '-X', 'utf8', bootstrap, '--script', ...arguments_],
        { cwd: ctx.cwd, env, shell: false, stdio: 'inherit' });
      child.once('error', reject);
      child.once('close', (code, signal) => resolve(code === null ? (signal === 'SIGINT' ? 130 : 1) : code));
    });
  } catch (error) {
    ctx.stderr.write(`[ERROR] ${error.message}\n`);
    return 2;
  }
}

module.exports = { localPath, runtimeSelection, main };
if (require.main === module) main(process.argv.slice(2)).then((code) => { process.exitCode = code; });
