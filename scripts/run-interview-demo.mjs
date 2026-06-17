import { spawn } from 'node:child_process';
import { access } from 'node:fs/promises';
import { constants as fsConstants } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const projectRoot = path.dirname(fileURLToPath(new URL('../package.json', import.meta.url)));
const candidates = [
    path.join(projectRoot, '.venv', 'Scripts', 'python.exe'),
    'python3',
    'python',
];

export function buildPythonArgs(userArgs = []) {
    const forwardedArgs = Array.isArray(userArgs) ? userArgs.map((arg) => String(arg)) : [];
    const hasSummaryArg = forwardedArgs.some((arg) => arg === '--summary' || arg.startsWith('--summary='));
    const args = ['scripts/run_interview_demo.py'];
    if (!hasSummaryArg) {
        args.push('--summary');
    }
    args.push(...forwardedArgs);
    return args;
}

async function resolvePython() {
    for (const candidate of candidates) {
        if (candidate.endsWith('.exe')) {
            try {
                await access(candidate, fsConstants.X_OK);
                return candidate;
            } catch {
                continue;
            }
        }
        return candidate;
    }
    return 'python';
}

export async function main(argv = process.argv.slice(2)) {
    const python = await resolvePython();
    const child = spawn(python, buildPythonArgs(argv), {
        cwd: projectRoot,
        stdio: 'inherit',
    });

    child.on('exit', (code, signal) => {
        if (signal) {
            process.exitCode = 1;
            return;
        }
        process.exitCode = code ?? 1;
    });

    return child;
}

const isDirectExecution = process.argv[1]
    ? path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
    : false;

if (isDirectExecution) {
    await main();
}
