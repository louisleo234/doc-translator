import { execFileSync, spawn, spawnSync } from 'child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { createServer } from 'http';
import { tmpdir } from 'os';
import { join } from 'path';

type Step = { name: string; run?: string };
type Job = { if?: string; needs?: string | string[]; steps: Step[] };

function workflow(filename = 'deploy.yml'): Record<string, Job> {
  const path = join(__dirname, '../../.github/workflows', filename);
  const script = 'print JSON.generate(YAML.load_file(ARGV[0]).fetch("jobs"))';
  return JSON.parse(execFileSync('ruby', ['-rjson', '-ryaml', '-e', script, path], { encoding: 'utf8' }));
}

function step(job: Job | undefined, name: string): string {
  const command = job?.steps.find(item => item.name === name)?.run;
  if (!command) throw new Error(`Missing workflow step: ${name}`);
  return command;
}

describe('deployment workflow', () => {
  it('uses the dedicated upstream credential only for fetching the private upstream', () => {
    const command = step(workflow('check-upstream.yml')['check-upstream'], 'Add upstream remote');
    const dir = mkdtempSync(join(tmpdir(), 'workflow-fetch-test-'));
    try {
      const header = Buffer.from('x-access-token:test-upstream-token').toString('base64');
      const fakeGit = `#!/bin/bash
if [[ "$1" == remote ]]; then exit 0; fi
if [[ "$1 $2 $3" == 'fetch upstream main' ]]; then
  [[ "$GIT_CONFIG_COUNT" == 2 && "$GIT_CONFIG_KEY_0" == 'http.https://github.com/.extraheader' && -z "$GIT_CONFIG_VALUE_0" && "$GIT_CONFIG_KEY_1" == 'http.https://github.com/.extraheader' && "$GIT_CONFIG_VALUE_1" == 'AUTHORIZATION: basic ${header}' ]]
  exit $?
fi
exit 1
`;
      writeFileSync(join(dir, 'git'), fakeGit, { mode: 0o700 });
      const env = { ...process.env, PATH: `${dir}:${process.env.PATH}`, UPSTREAM_READ_TOKEN: 'test-upstream-token' };
      const good = spawnSync('bash', ['-e', '-o', 'pipefail', '-c', command], { env, encoding: 'utf8' });
      expect(good.status).toBe(0);
      expect(good.stdout + good.stderr).not.toContain('test-upstream-token');
      const missing = spawnSync('bash', ['-e', '-o', 'pipefail', '-c', command], { env: { ...env, UPSTREAM_READ_TOKEN: '' }, encoding: 'utf8' });
      expect(missing.status).not.toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('creates a unique sync branch without deleting an existing branch', () => {
    const command = step(workflow('check-upstream.yml')['check-upstream'], 'Prepare sync branch');
    const dir = mkdtempSync(join(tmpdir(), 'workflow-git-test-'));
    try {
      writeFileSync(join(dir, 'git'), '#!/bin/bash\nprintf "%s\\n" "$*" >> "$GIT_TEST_LOG"\n', { mode: 0o700 });
      const run = (id: string) => {
        const envPath = join(dir, `env-${id}`);
        const logPath = join(dir, `log-${id}`);
        const env = { ...process.env, PATH: `${dir}:${process.env.PATH}`, GITHUB_ENV: envPath, GITHUB_OUTPUT: join(dir, `out-${id}`), GITHUB_RUN_ID: id, GIT_TEST_LOG: logPath };
        const result = spawnSync('bash', ['-e', '-o', 'pipefail', '-c', command], { env, encoding: 'utf8' });
        expect(result.status).toBe(0);
        expect(readFileSync(logPath, 'utf8')).not.toContain('--delete');
        return readFileSync(envPath, 'utf8');
      };
      expect(run('101')).not.toEqual(run('102'));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('preserves the running MCP configuration and rejects a mismatched JWT secret', () => {
    const command = step(workflow().deploy, 'Preserve MCP configuration');
    const dir = mkdtempSync(join(tmpdir(), 'workflow-test-'));
    try {
      const fakeAws = `#!/bin/bash
case "$1 $2" in
  'cloudformation describe-stack-resource') echo service-arn ;;
  'ecs describe-services') echo task-arn ;;
  'ecs describe-task-definition') echo '[{"name":"MCP_ALLOWED_HOSTS","value":"host.example"},{"name":"MCP_ALLOWED_ORIGINS","value":"http://host.example"},{"name":"JWT_SECRET","value":"expected-test-secret"}]' ;;
  *) exit 1 ;;
esac
`;
      writeFileSync(join(dir, 'aws'), fakeAws, { mode: 0o700 });
      const envPath = join(dir, 'env');
      const env = { ...process.env, PATH: `${dir}:${process.env.PATH}`, GITHUB_ENV: envPath, JWT_SECRET: 'expected-test-secret' };
      const good = spawnSync('bash', ['-e', '-o', 'pipefail', '-c', command], { env, encoding: 'utf8' });
      expect(good.status).toBe(0);
      expect(readFileSync(envPath, 'utf8')).toContain('MCP_ALLOWED_HOSTS=host.example');
      expect(readFileSync(envPath, 'utf8')).toContain('MCP_ALLOWED_ORIGINS=http://host.example');
      const bad = spawnSync('bash', ['-e', '-o', 'pipefail', '-c', command], { env: { ...env, JWT_SECRET: 'different' }, encoding: 'utf8' });
      expect(bad.status).not.toBe(0);
      expect(bad.stdout + bad.stderr).not.toContain('expected-test-secret');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('sends the final deployment result and rejects a WeCom API error', async () => {
    const job = workflow()['notify-result'];
    expect(job?.if).toContain('always()');
    expect(job?.needs).toContain('deploy');
    const command = step(job, 'Send deployment result');
    const requests: string[] = [];
    let errcode = 0;
    const server = createServer((req, res) => {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', () => {
        requests.push(body);
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify({ errcode }));
      });
    });
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
    try {
      const address = server.address();
      if (!address || typeof address === 'string') throw new Error('No test server address');
      const run = (script = command) => new Promise<number | null>(resolve => {
        const child = spawn('bash', ['-e', '-o', 'pipefail', '-c', script], {
          env: { ...process.env, WECHAT_WEBHOOK_URL: `http://127.0.0.1:${address.port}`, DEPLOY_RESULT: 'failure', GITHUB_SERVER_URL: 'https://github.example', GITHUB_REPOSITORY: 'org/repo', GITHUB_RUN_ID: '123', GITHUB_SHA: 'abcdef1234', NEW_COMMITS: 'quoted "commit" $(echo should-not-execute)' },
        });
        child.on('close', resolve);
      });
      expect(await run()).toBe(0);
      const payload = JSON.parse(requests[0]);
      expect(payload.msgtype).toBe('markdown');
      expect(payload.markdown.content).toContain('失败');
      expect(payload.markdown.content).toContain('/org/repo/actions/runs/123');
      const upstream = workflow('check-upstream.yml')['notify-failure'];
      expect(upstream?.if).toContain('failure');
      expect(upstream?.needs).toContain('check-upstream');
      expect(await run(step(upstream, 'Send upstream failure notification'))).toBe(0);
      expect(JSON.parse(requests[1]).markdown.content).toContain('上游检查失败');
      expect(await run(step(workflow('check-upstream.yml')['check-upstream'], 'Notify WeChat - deploy triggered'))).toBe(0);
      expect(JSON.parse(requests[2]).markdown.content).toContain('quoted "commit" $(echo should-not-execute)');
      errcode = 93000;
      expect(await run()).not.toBe(0);
    } finally {
      await new Promise<void>(resolve => server.close(() => resolve()));
    }
  });
});
