import test from 'node:test';
import assert from 'node:assert/strict';

import { renderExportCenterPageShell } from '../../src/renderer/js/app-shell/pages/export-center.js';
import { resolveRagDirFromExportResult } from '../../src/renderer/js/pages/ExportCenterPage.js';

test('export center shell exposes an independent export-rag toggle', () => {
    const markup = renderExportCenterPageShell();
    assert.equal(markup.includes('id="export-rag-config-enabled"'), true);
    assert.equal(markup.includes('启用导出语料检索通道'), true);
});

test('resolveRagDirFromExportResult prefers server rag_dir when available', () => {
    const ragDir = resolveRagDirFromExportResult({
        output_dir: 'data/chat_exports',
        rag_dir: 'data/chat_exports/聊天记录',
    });
    assert.equal(ragDir, 'data/chat_exports/聊天记录');
});

test('resolveRagDirFromExportResult builds path from output dir using matching separator', () => {
    const win = resolveRagDirFromExportResult({ output_dir: 'data\\chat_exports' });
    const posix = resolveRagDirFromExportResult({ output_dir: 'data/chat_exports' });
    assert.equal(win, 'data\\chat_exports\\聊天记录');
    assert.equal(posix, 'data/chat_exports/聊天记录');
});
