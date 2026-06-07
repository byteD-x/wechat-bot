import { apiService } from '../../services/ApiService.js';
import { toast } from '../../services/NotificationService.js';

export const TOOL_WORKFLOW_TOOLS = Object.freeze([
    { value: 'config_audit', label: '配置审计' },
    { value: 'prompt_preview', label: 'Prompt 预览' },
    { value: 'readiness_check', label: '启动准备检查' },
    { value: 'eval_latest', label: '最新评测' },
    { value: 'cost_summary', label: '成本摘要' },
]);

const DEFAULT_SEQUENCE = ['config_audit', 'prompt_preview', 'readiness_check'];
const STEP_SELECTORS = [
    '#dashboard-tool-workflow-step-1',
    '#dashboard-tool-workflow-step-2',
    '#dashboard-tool-workflow-step-3',
];

function getApiService(deps = {}) {
    return deps.apiService || apiService;
}

function getToast(deps = {}) {
    return deps.toast || toast;
}

function asArray(value) {
    return Array.isArray(value) ? value : [];
}

function formatCurrencyGroups(groups) {
    const values = asArray(groups)
        .map((item) => {
            const currency = String(item?.currency || '').trim();
            const totalCost = Number(item?.total_cost || 0);
            return currency ? `${currency} ${totalCost.toFixed(4)}` : '';
        })
        .filter(Boolean);
    return values.length ? values.slice(0, 2).join('、') : '暂无费用';
}

function normalizeTool(value) {
    const tool = String(value || '').trim();
    return TOOL_WORKFLOW_TOOLS.some((item) => item.value === tool) ? tool : '';
}

function getToolLabel(tool) {
    return TOOL_WORKFLOW_TOOLS.find((item) => item.value === tool)?.label || tool || '未知工具';
}

function getState(page) {
    if (!page._toolWorkflowState || typeof page._toolWorkflowState !== 'object') {
        page._toolWorkflowState = {
            running: false,
            result: null,
            feedback: '尚未执行工具流',
            feedbackState: 'idle',
        };
    }
    return page._toolWorkflowState;
}

function setFeedback(page, message, state = 'idle') {
    const workflowState = getState(page);
    workflowState.feedback = String(message || '').trim();
    workflowState.feedbackState = state;
}

function isConnected(page) {
    return !!page.getState?.('bot.connected');
}

function updateButton(button, disabled, label) {
    if (!button) {
        return;
    }
    button.disabled = !!disabled;
    if (!label) {
        return;
    }
    const span = button.querySelector?.('span');
    if (span) {
        span.textContent = label;
    } else {
        button.textContent = label;
    }
}

function getSampleMessage(page) {
    const value = String(page.$?.('#dashboard-tool-workflow-sample')?.value || '').trim();
    return value || '你好，帮我确认当前运行准备状态。';
}

function buildPayload(tool, page) {
    if (tool !== 'prompt_preview') {
        return {};
    }
    return {
        sample: {
            chat_name: 'tool_workflow_preview',
            sender: 'preview_user',
            message: getSampleMessage(page),
            is_group: false,
        },
    };
}

export function buildToolWorkflowSteps(page) {
    const continueOnError = !!page.$?.('#dashboard-tool-workflow-continue')?.checked;
    return STEP_SELECTORS
        .map((selector) => normalizeTool(page.$?.(selector)?.value))
        .filter(Boolean)
        .map((tool) => ({
            tool,
            payload: buildPayload(tool, page),
            ...(continueOnError ? { continue_on_error: true } : {}),
        }));
}

function getRecoveryAdvice(item) {
    const errorType = String(item?.error_type || '').trim();
    const tool = String(item?.tool || '').trim();
    if (errorType === 'unsupported_tool') {
        return '只使用页面下拉列表里的白名单工具，再重新执行。';
    }
    if (errorType === 'schema_validation') {
        return tool === 'prompt_preview'
            ? '检查示例消息是否为空或格式异常；也可以先执行 dry-run。'
            : '检查该工具的参数来源，当前界面不会发送任意 JSON。';
    }
    if (errorType === 'timeout') {
        return '稍后重试；若后端繁忙，先刷新运行状态再执行。';
    }
    if (errorType === 'permission_denied') {
        return '该工具未获得当前管理权限，保持白名单不变并查看后端日志。';
    }
    if (errorType === 'invalid_tool_result') {
        return '工具返回不是 JSON 对象，保留 trace 后检查对应后端工具实现。';
    }
    return '保留失败 trace，先查看日志或改用 dry-run 缩小问题范围。';
}

function formatOutputSummary(item) {
    const output = item?.output && typeof item.output === 'object' ? item.output : {};
    if (output.dry_run) {
        return 'dry-run 已跳过真实执行';
    }
    if (item?.tool === 'prompt_preview') {
        const summary = output.summary && typeof output.summary === 'object' ? output.summary : {};
        const chars = Number(summary.chars || 0);
        const lines = Number(summary.lines || 0);
        return chars || lines ? `Prompt 摘要：${chars} 字符，${lines} 行` : 'Prompt 预览已返回摘要';
    }
    if (item?.tool === 'readiness_check') {
        const ready = output.ready === true ? '已就绪' : output.ready === false ? '未就绪' : '已返回';
        const blocking = Number(output.blockingCount ?? output.blocking_count ?? 0);
        return blocking ? `${ready}，阻塞项 ${blocking} 个` : ready;
    }
    if (item?.tool === 'eval_latest') {
        if (output.has_report === false) {
            return '暂无评测报告';
        }
        const summary = output.summary && typeof output.summary === 'object' ? output.summary : {};
        const totalCases = Number(summary.total_cases || 0);
        const passed = summary.passed === true ? '通过' : summary.passed === false ? '未通过' : '已返回';
        const regressions = Number(output.regression_count || 0);
        return totalCases
            ? `最新评测：${totalCases} 个用例，${passed}，回归 ${regressions} 项`
            : `最新评测${passed}，回归 ${regressions} 项`;
    }
    if (item?.tool === 'cost_summary') {
        const overview = output.overview && typeof output.overview === 'object' ? output.overview : {};
        const replyCount = Number(overview.reply_count || 0);
        const totalTokens = Number(overview.total_tokens || 0);
        const modelCount = Number(output.model_count || 0);
        const reviewQueueCount = Number(output.review_queue_count || 0);
        const costText = formatCurrencyGroups(overview.currency_groups);
        return `成本摘要：回复 ${replyCount} 条，Token ${totalTokens}，模型 ${modelCount} 个，复核 ${reviewQueueCount} 条，${costText}`;
    }
    if (item?.tool === 'config_audit') {
        const dormant = asArray(output.dormant_paths).length;
        const unknown = asArray(output.unknown_override_paths).length;
        return dormant || unknown ? `休眠配置 ${dormant} 项，未知覆盖 ${unknown} 项` : '配置审计已完成';
    }
    return '工具已返回结果';
}

function appendTextNode(documentObj, parent, className, text) {
    const node = documentObj.createElement('div');
    node.className = className;
    node.textContent = text;
    parent.appendChild(node);
    return node;
}

function renderTrace(page) {
    const state = getState(page);
    const traceNode = page.$?.('#dashboard-tool-workflow-trace');
    if (!traceNode || typeof document === 'undefined') {
        return;
    }
    const documentObj = traceNode.ownerDocument || document;
    traceNode.textContent = '';
    const trace = asArray(state.result?.trace);

    if (state.running) {
        appendTextNode(documentObj, traceNode, 'tool-workflow-empty', '正在执行，等待后端返回逐步 trace...');
        return;
    }
    if (!trace.length) {
        appendTextNode(documentObj, traceNode, 'tool-workflow-empty', '尚未执行工具流');
        return;
    }

    trace.forEach((item) => {
        const status = String(item?.status || 'unknown');
        const row = documentObj.createElement('div');
        row.className = `tool-workflow-trace-item ${status === 'error' ? 'is-error' : status === 'skipped' ? 'is-skipped' : 'is-ok'}`;

        appendTextNode(
            documentObj,
            row,
            'tool-workflow-trace-title',
            `#${Number(item?.index || 0)} ${getToolLabel(item?.tool)} · ${status}`
        );
        appendTextNode(
            documentObj,
            row,
            'tool-workflow-trace-meta',
            `耗时 ${Number(item?.duration_ms || 0).toFixed(1)} ms · 尝试 ${Number(item?.attempts || 0)} 次 · 重试上限 ${Number(item?.retry_count || 0)}`
        );
        if (status === 'error') {
            appendTextNode(documentObj, row, 'tool-workflow-trace-error', `${item?.error_type || 'tool_error'}：${item?.error || '工具执行失败'}`);
            appendTextNode(documentObj, row, 'tool-workflow-trace-advice', getRecoveryAdvice(item));
        } else {
            appendTextNode(documentObj, row, 'tool-workflow-trace-output', formatOutputSummary(item));
        }
        traceNode.appendChild(row);
    });
}

export function renderToolWorkflowPanel(page) {
    const state = getState(page);
    const connected = isConnected(page);
    const steps = buildToolWorkflowSteps(page);
    const feedback = page.$?.('#dashboard-tool-workflow-feedback');
    const meta = page.$?.('#dashboard-tool-workflow-meta');
    const dryRunButton = page.$?.('#btn-tool-workflow-dry-run');
    const runButton = page.$?.('#btn-run-tool-workflow');
    const resetButton = page.$?.('#btn-reset-tool-workflow');

    if (feedback) {
        feedback.textContent = state.feedback || '尚未执行工具流';
        feedback.dataset.state = state.feedbackState || 'idle';
    }
    if (meta) {
        meta.textContent = connected
            ? `已选择 ${steps.length} 个工具：${steps.map((item) => getToolLabel(item.tool)).join('、') || '无'}`
            : '请先连接 Python 服务后执行工具流。';
    }
    updateButton(dryRunButton, !connected || state.running || !steps.length, state.running ? '执行中...' : '先 dry-run');
    updateButton(runButton, !connected || state.running || !steps.length, state.running ? '执行中...' : '执行工具流');
    updateButton(resetButton, state.running, '恢复默认');
    renderTrace(page);
}

export function resetToolWorkflow(page) {
    STEP_SELECTORS.forEach((selector, index) => {
        const select = page.$?.(selector);
        if (select) {
            select.value = DEFAULT_SEQUENCE[index] || '';
        }
    });
    const sample = page.$?.('#dashboard-tool-workflow-sample');
    if (sample) {
        sample.value = '你好，帮我确认当前运行准备状态。';
    }
    const continueOnError = page.$?.('#dashboard-tool-workflow-continue');
    if (continueOnError) {
        continueOnError.checked = false;
    }
    const state = getState(page);
    state.result = null;
    setFeedback(page, '已恢复默认工具流。', 'idle');
    renderToolWorkflowPanel(page);
}

export async function runToolWorkflow(page, options = {}, deps = {}) {
    const state = getState(page);
    const currentToast = getToast(deps);
    const currentApiService = getApiService(deps);
    const dryRun = !!options?.dryRun;
    const steps = buildToolWorkflowSteps(page);

    if (!isConnected(page)) {
        setFeedback(page, '请先连接 Python 服务后执行工具流。', 'warning');
        renderToolWorkflowPanel(page);
        currentToast.warning('Python 服务未连接，无法执行工具流');
        return null;
    }
    if (!steps.length) {
        setFeedback(page, '请至少选择一个白名单工具。', 'warning');
        renderToolWorkflowPanel(page);
        return null;
    }

    state.running = true;
    state.result = null;
    setFeedback(page, dryRun ? '正在执行 dry-run...' : '正在执行工具流...', 'loading');
    renderToolWorkflowPanel(page);

    try {
        const result = await currentApiService.runToolWorkflow({
            dry_run: dryRun,
            steps,
        });
        state.result = result;
        if (result?.success) {
            setFeedback(page, dryRun ? 'dry-run 已完成，未真实执行工具。' : '工具流执行完成。', 'success');
            currentToast.success(dryRun ? 'Tool Workflow dry-run 已完成' : 'Tool Workflow 已完成');
        } else {
            setFeedback(page, result?.message || '工具流未完成，请查看失败步骤。', 'warning');
            currentToast.warning(state.feedback);
        }
        return result;
    } catch (error) {
        const traceResult = error?.data?.trace
            ? {
                success: false,
                code: error.data.code || error.code || 'bad_workflow',
                message: error.data.message || error.message || '工具流执行失败',
                trace: error.data.trace,
            }
            : null;
        if (traceResult) {
            state.result = traceResult;
            setFeedback(page, traceResult.message, 'warning');
            currentToast.warning(traceResult.message);
            return traceResult;
        }
        console.error('[DashboardPage] tool workflow failed:', error);
        setFeedback(page, currentToast.getErrorMessage(error, '工具流执行失败'), 'error');
        currentToast.error(state.feedback);
        return null;
    } finally {
        state.running = false;
        renderToolWorkflowPanel(page);
    }
}
