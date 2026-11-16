import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { DocTranslationStack, DocTranslationStackProps } from '../lib/doc-translation-stack';

function backendEnvironment(props: Partial<DocTranslationStackProps> = {}) {
  const stack = new DocTranslationStack(new cdk.App(), 'Test', {
    s3Bucket: 'test-documents', jwtSecret: 'test-secret', ...props,
  });
  const tasks = Template.fromStack(stack).findResources('AWS::ECS::TaskDefinition');
  const containers = Object.values(tasks).flatMap(task => task.Properties.ContainerDefinitions);
  const backend = containers.find(container => container.Environment?.some(
    (entry: { Name: string }) => entry.Name === 'JWT_SECRET'));
  return Object.fromEntries(backend.Environment.map(
    (entry: { Name: string; Value: unknown }) => [entry.Name, entry.Value]));
}

test('MCP defaults allow public and enabled internal ALB plus loopbacks', () => {
  const env = backendEnvironment({ enableInternalAlb: true });
  const hosts = JSON.stringify(env.MCP_ALLOWED_HOSTS);
  expect(hosts).toContain('localhost:*');
  expect(hosts).toContain('127.0.0.1:*');
  expect(hosts).toContain('[::1]:*');
  expect(hosts).toContain('InternalAlb');
  expect(hosts.match(/DNSName/g)).toHaveLength(2);
  expect(JSON.stringify(env.MCP_ALLOWED_ORIGINS)).toContain('InternalAlb');
});

test('MCP explicit host and origin values reach backend task environment', () => {
  const env = backendEnvironment({
    mcpAllowedHosts: 'docs.example.com,private.example.com',
    mcpAllowedOrigins: 'https://docs.example.com',
  });
  expect(env.MCP_ALLOWED_HOSTS).toBe('docs.example.com,private.example.com');
  expect(env.MCP_ALLOWED_ORIGINS).toBe('https://docs.example.com');
});


test('MCP public-only defaults omit internal ALB and reject blanket allowlists', () => {
  const hosts = JSON.stringify(backendEnvironment().MCP_ALLOWED_HOSTS);
  expect(hosts.match(/DNSName/g)).toHaveLength(1);
  expect(hosts).not.toContain('InternalAlb');
  expect(() => backendEnvironment({ mcpAllowedHosts: '*' })).toThrow('explicit hosts');
  expect(() => backendEnvironment({ mcpAllowedOrigins: '*' })).toThrow('explicit hosts');
});
