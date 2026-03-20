import test from 'node:test';
import assert from 'node:assert/strict';

import {
    collectSettingsPayload,
    composeSystemPromptTemplate,
    extractEditableSystemPrompt,
    fillSettingsForm,
    getSystemPromptFixedBlock,
} from '../../src/renderer/js/pages/settings/form-codec.js';
import { installDomStub } from './dom-stub.mjs';

function withDom(run) {
    const env = installDomStub();
    try {
        run(env);
    } finally {
        env.restore();
    }
}

test('fillSettingsForm fills scoped fields and preserves unrelated inputs', () => withDom(({ document, registerElement, createPage }) => {
    const selectors = {
        '#setting-self-name': document.createElement('input'),
        '#setting-log-level': document.createElement('input'),
        '#setting-ignore-names': document.createElement('textarea'),
        '#setting-system-prompt-editable': document.createElement('textarea'),
        '#setting-system-prompt-fixed': document.createElement('textarea'),
        '#setting-random-delay-min-sec': document.createElement('input'),
        '#setting-random-delay-max-sec': document.createElement('input'),
    };
    const langsmithStatus = document.createElement('input');
    registerElement('agent-langsmith-key-status', langsmithStatus);

    selectors['#setting-log-level'].value = 'UNCHANGED';
    const page = createPage(selectors);

    fillSettingsForm(page, {
        bot: {
            self_name: '小助手',
            ignore_names: ['Alice', 'Bob'],
            system_prompt: composeSystemPromptTemplate('像真人聊天，不要太官腔。'),
            random_delay_range_sec: [2, 5],
        },
        logging: {
            level: 'INFO',
        },
        agent: {
            langsmith_api_key_configured: true,
        },
    }, {
        ids: new Set([
            'setting-self-name',
            'setting-ignore-names',
            'setting-system-prompt-editable',
            'setting-random-delay-min-sec',
            'setting-random-delay-max-sec',
        ]),
    });

    assert.equal(selectors['#setting-self-name'].value, '小助手');
    assert.equal(selectors['#setting-ignore-names'].value, 'Alice\nBob');
    assert.equal(selectors['#setting-system-prompt-editable'].value, '像真人聊天，不要太官腔。');
    assert.equal(selectors['#setting-system-prompt-fixed'].value, getSystemPromptFixedBlock());
    assert.equal(selectors['#setting-random-delay-min-sec'].value, '2');
    assert.equal(selectors['#setting-random-delay-max-sec'].value, '5');
    assert.equal(selectors['#setting-log-level'].value, 'UNCHANGED');
    assert.equal(langsmithStatus.value, '已配置（已隐藏）');
}));

test('collectSettingsPayload respects scope ids and skips api presets when disabled', () => withDom(({ document, createPage }) => {
    const selectors = {
        '#setting-self-name': document.createElement('input'),
        '#setting-log-level': document.createElement('input'),
        '#setting-ignore-names': document.createElement('textarea'),
        '#setting-system-prompt-editable': document.createElement('textarea'),
        '#setting-system-prompt-overrides': document.createElement('textarea'),
        '#setting-random-delay-min-sec': document.createElement('input'),
        '#setting-random-delay-max-sec': document.createElement('input'),
    };

    selectors['#setting-self-name'].value = '新名字';
    selectors['#setting-log-level'].value = 'DEBUG';
    selectors['#setting-ignore-names'].value = 'Alice\nBob';
    selectors['#setting-system-prompt-editable'].value = '简短回复，贴近微信口语。';
    selectors['#setting-system-prompt-overrides'].value = 'foo|bar\nbaz|qux';
    selectors['#setting-random-delay-min-sec'].value = '3';
    selectors['#setting-random-delay-max-sec'].value = '8';

    const page = createPage(selectors);
    const payload = collectSettingsPayload(page, {
        ids: new Set([
            'setting-self-name',
            'setting-ignore-names',
            'setting-system-prompt-editable',
            'setting-system-prompt-overrides',
            'setting-random-delay-min-sec',
            'setting-random-delay-max-sec',
        ]),
        includeApiPresets: false,
    });

    assert.deepEqual(payload, {
        bot: {
            self_name: '新名字',
            ignore_names: ['Alice', 'Bob'],
            system_prompt: composeSystemPromptTemplate('简短回复，贴近微信口语。'),
            system_prompt_overrides: {
                foo: 'bar',
                baz: 'qux',
            },
            random_delay_range_sec: [3, 8],
        },
    });
    assert.equal(payload.logging, undefined);
    assert.equal(payload.api, undefined);
}));

test('system prompt helpers strip reserved injection block before editing', () => {
    const fullPrompt = [
        '像本人一样聊天。',
        '',
        getSystemPromptFixedBlock(),
    ].join('\n');

    assert.equal(extractEditableSystemPrompt(fullPrompt), '像本人一样聊天。');
    assert.equal(composeSystemPromptTemplate('像本人一样聊天。'), fullPrompt);
});
