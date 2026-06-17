import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildPythonArgs, buildPythonStartupHelp } from '../../scripts/run-interview-demo.mjs';

test('package exposes one-command interview demo entry', () => {
    const pkg = JSON.parse(readFileSync('package.json', 'utf8'));

    assert.equal(
        pkg.scripts['demo:interview'],
        'node scripts/run-interview-demo.mjs'
    );
});

test('interview demo npm launcher prefers project virtualenv, writes summary, and forwards args', () => {
    const launcher = readFileSync('scripts/run-interview-demo.mjs', 'utf8');

    assert.match(launcher, /['"]\.venv['"]/);
    assert.match(launcher, /run_interview_demo\.py/);
    assert.match(launcher, /--summary/);
    assert.match(launcher, /process\.argv\.slice\(2\)/);
    assert.match(launcher, /isDirectExecution/);
});

test('interview demo launcher injects summary only when needed', () => {
    assert.deepEqual(buildPythonArgs([]), [
        'scripts/run_interview_demo.py',
        '--summary',
    ]);
    assert.deepEqual(buildPythonArgs(['--skip-eval', '--json']), [
        'scripts/run_interview_demo.py',
        '--summary',
        '--skip-eval',
        '--json',
    ]);
    assert.deepEqual(buildPythonArgs(['--summary', 'custom.md', '--json']), [
        'scripts/run_interview_demo.py',
        '--summary',
        'custom.md',
        '--json',
    ]);
    assert.deepEqual(buildPythonArgs(['--summary=custom.md']), [
        'scripts/run_interview_demo.py',
        '--summary=custom.md',
    ]);
});

test('interview demo launcher explains how to recover when Python cannot start', () => {
    const help = buildPythonStartupHelp('python', new Error('spawn python ENOENT'));

    assert.match(help, /Failed to start Python for the interview demo: python/);
    assert.match(help, /python -m venv \.venv/);
    assert.match(help, /pip install -r requirements\.txt/);
    assert.match(help, /npm run demo:interview/);
    assert.match(help, /run_interview_demo\.py --summary/);
});
