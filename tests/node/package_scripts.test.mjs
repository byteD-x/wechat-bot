import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('package exposes one-command interview demo entry', () => {
    const pkg = JSON.parse(readFileSync('package.json', 'utf8'));

    assert.equal(
        pkg.scripts['demo:interview'],
        'node scripts/run-interview-demo.mjs'
    );
});

test('interview demo npm launcher prefers project virtualenv and writes summary', () => {
    const launcher = readFileSync('scripts/run-interview-demo.mjs', 'utf8');

    assert.match(launcher, /['"]\.venv['"]/);
    assert.match(launcher, /run_interview_demo\.py/);
    assert.match(launcher, /--summary/);
});
