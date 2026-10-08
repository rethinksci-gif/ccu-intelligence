import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
const python = existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python3';
for (const command of ['validate', 'export']) {
  const result = spawnSync(python, ['-m', 'ccu_intelligence.cli', command], {
    stdio: 'inherit',
    env: { ...process.env, PYTHONPATH: 'src' },
  });
  if (result.error || result.status !== 0) {
    console.error('Data validation failed. Install requirements.lock before building.');
    process.exit(result.status || 1);
  }
}
