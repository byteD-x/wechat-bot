import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

test('renderer module import does not emit typeless package warning', () => {
    const result = spawnSync(
        process.execPath,
        [
            '--input-type=module',
            '--eval',
            "import('./src/renderer/js/services/ApiService.js').catch((error) => { console.error(error); process.exit(1); });",
        ],
        {
            cwd: process.cwd(),
            encoding: 'utf8',
        }
    );

    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.equal(result.stderr.includes('MODULE_TYPELESS_PACKAGE_JSON'), false, result.stderr);
});
