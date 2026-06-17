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

const python = await resolvePython();
const userArgs = process.argv.slice(2);
const child = spawn(python, ['scripts/run_interview_demo.py', '--summary', ...userArgs], {
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
