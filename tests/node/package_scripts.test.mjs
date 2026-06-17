import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { buildPythonArgs } from '../../scripts/run-interview-demo.mjs';

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
