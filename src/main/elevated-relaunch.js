function quotePowerShellString(value = '') {
    return `'${String(value ?? '').replace(/'/g, "''")}'`;
}

function buildElevatedLaunchPlan({
    processLike = process,
    appPath = '',
} = {}) {
    const execPath = String(processLike?.execPath || '').trim();
    if (!execPath) {
        throw new Error('Missing executable path for elevated relaunch');
    }

    const argv = Array.isArray(processLike?.argv) ? processLike.argv.slice() : [];
    const usesDefaultApp = !!processLike?.defaultApp;
    const resolvedAppPath = String(appPath || argv[1] || '').trim();

    const args = usesDefaultApp
        ? [resolvedAppPath, ...argv.slice(2)]
        : argv.slice(1);

    if (usesDefaultApp && !resolvedAppPath) {
        throw new Error('Missing Electron app path for elevated relaunch');
    }

    return {
        filePath: execPath,
        args,
    };
}

function buildElevatedPowerShellScript({ filePath, args = [] } = {}) {
    if (!filePath) {
        throw new Error('Missing executable path for PowerShell relaunch');
    }

    const argumentList = Array.isArray(args) && args.length > 0
        ? ` -ArgumentList @(${args.map((item) => quotePowerShellString(item)).join(', ')})`
        : '';

    return [
        "$ErrorActionPreference = 'Stop'",
        `Start-Process -FilePath ${quotePowerShellString(filePath)}${argumentList} -Verb RunAs | Out-Null`,
    ].join('; ');
}

function buildElevatedPowerShellCommand(options = {}) {
    const script = buildElevatedPowerShellScript(options);
    return Buffer.from(script, 'utf16le').toString('base64');
}

async function launchElevatedApp({
    execFileImpl,
    processLike = process,
    appPath = '',
} = {}) {
    if (typeof execFileImpl !== 'function') {
        throw new Error('Missing execFile implementation for elevated relaunch');
    }

    const plan = buildElevatedLaunchPlan({
        processLike,
        appPath,
    });
    const encodedCommand = buildElevatedPowerShellCommand(plan);

    await new Promise((resolve, reject) => {
        execFileImpl(
            'powershell.exe',
            [
                '-NoProfile',
                '-NonInteractive',
                '-ExecutionPolicy',
                'Bypass',
                '-EncodedCommand',
                encodedCommand,
            ],
            (error, stdout, stderr) => {
                if (!error) {
                    resolve();
                    return;
                }

                const detail = String(stderr || stdout || error.message || '').trim();
                if (/cancel|1223|用户取消|已取消/i.test(detail)) {
                    const cancelError = new Error('用户取消了管理员权限授权');
                    cancelError.code = 'uac_cancelled';
                    reject(cancelError);
                    return;
                }

                reject(new Error(detail || 'Unable to relaunch app with administrator privileges'));
            },
        );
    });

    return {
        success: true,
        filePath: plan.filePath,
        args: plan.args,
    };
}

module.exports = {
    buildElevatedLaunchPlan,
    buildElevatedPowerShellScript,
    buildElevatedPowerShellCommand,
    launchElevatedApp,
};
