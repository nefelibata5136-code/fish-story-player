/** Read-only-installed-runtime DSH MCP integration check; no LLM/provider.
 *
 * Usage: node scripts/check_dsh_bridge.mjs --runtime <DSH directory>
 *   --config <agent-config JSON> [--story demo|detroit] [--campaign]
 *
 * Uses official installed Cordis, SystemPrompt, ToolRuntime and MCP bridge.
 * Creates an isolated scoped tool registry, never uses a daily life session.
 * Decisions are deterministic script choices, not an autonomous model run.
 */
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';

const options = new Map();
for (let i = 2; i < process.argv.length; i++) {
  const key = process.argv[i];
  options.set(key, key === '--campaign' ? true : process.argv[++i]);
}
if (!options.get('--runtime') || !options.get('--config')) {
  throw new Error('Provide --runtime and --config. No default live profile is used.');
}
const imported = name => import(pathToFileURL(join(options.get('--runtime'), 'node_modules',
  '@deepseek-ai', name, 'lib', 'index.js')).href);
const [{ Context }, { SystemPrompt }, { ToolRuntime }, Mcp, { createScope }] = await Promise.all([
  imported('cordis'), imported('dsh-system-prompt'), imported('dsh-tools'), imported('dsh-mcp-client'), imported('dsh-scope')
]);
const generated = JSON.parse(await readFile(options.get('--config'), 'utf8'));
const native = generated.dsh_config[0].config;
const ctx = new Context();
const fibers = [];
let scope;
let calls = 0;
const identity = { testScopeId: randomUUID() };
try {
  fibers.push(await ctx.plugin(SystemPrompt, { includeHarnessIdentity: false }));
  fibers.push(await ctx.plugin(ToolRuntime, { mode: 'native' }));
  scope = createScope(ctx, identity);
  fibers.push(await scope.ctx.plugin(Mcp, native));
  const names = ctx.tools.schemas(identity).map(tool => tool.name);
  if (!names.includes('mcp__fish-story__game_start') || !names.includes('mcp__fish-story__game_choose')) {
    throw new Error('Native DSH scope did not discover the expected game tools.');
  }
  async function call(name, args = {}) {
    calls++;
    const result = await ctx.tools.execute({ callId: randomUUID(), name: 'mcp__fish-story__' + name,
      arguments: args, agent: identity, signal: AbortSignal.timeout(150000) });
    if (result.isError) throw new Error('DSH bridge call failed: ' + name + ' / ' + JSON.stringify(result.error));
    const value = result.value;
    if (value.structuredContent) return value.structuredContent;
    const texts = value.content?.filter(item => item.type === 'text').map(item => item.text) || [];
    if (texts.length === 1) return JSON.parse(texts[0]);
    throw new Error('Expected one structured game response.');
  }
  const campaigns = [];
  let recapUpdates = 0;
  async function finishRecaps(game) {
    while (game.status === 'recap_required') {
      const task = game.recap.pending_tasks[0];
      await call('game_recap_read', { session_id: game.session_id, task_id: task.task_id });
      await call('game_recap_update', { session_id: game.session_id, task_id: task.task_id,
        text: '脚本协议验收：本章已完成。本段仅验证玩家提交的摘要写入、隔离和恢复，不冒充模型对情节的理解。',
        operation_id: randomUUID() });
      recapUpdates++;
      game = await call('game_view', { session_id: game.session_id });
    }
    return game;
  }
  for (const style of options.get('--play-style') ? [options.get('--play-style')] : ['self_aware', 'immersive']) {
    let game = style === 'self_aware' && options.get('--resume')
      ? await call('game_open', { session_id: options.get('--resume') })
      : await call('game_start', { story_id: options.get('--story') || 'demo', play_style: style,
        save_name: 'DSH bridge verification ' + style });
    const session = game.session_id;
    const baseline = game.accepted_choices;
    const firstRequest = game.current?.request_id;
    const point = await call('game_save_checkpoint', { session_id: session, name: 'First scene', operation_id: randomUUID() });
    await call('game_pause', { session_id: session });
    game = await call('game_resume', { session_id: session });
    if (game.current?.request_id !== firstRequest) throw new Error('Pause/resume changed pending request.');
    const maxSteps = options.get('--campaign') ? 500 : 1;
    let steps = 0;
    while ((game.status === 'waiting' || game.status === 'recap_required') && steps < maxSteps) {
      game = await finishRecaps(game);
      if (game.status !== 'waiting') break;
      const current = game.current;
      game = await call('game_choose', { session_id: session, request_id: current.request_id,
        choice: current.choices[0].number });
      steps++;
    }
    game = await finishRecaps(game);
    if (options.get('--campaign') && game.status !== 'complete') throw new Error('Campaign did not complete.');
    const branch = await call('game_load_checkpoint', { session_id: session,
      point_id: point.id, name: 'Preserved original', operation_id: randomUUID() });
    if (branch.session_id === session || branch.accepted_choices !== baseline) throw new Error('Checkpoint did not create a fresh branch.');
    const preserved = await call('game_open', { session_id: session });
    if (preserved.accepted_choices !== steps + baseline) throw new Error('Loading a branch changed original choices.');
    const memory = await call('game_export', { session_id: session, format: 'memory' });
    if (!memory.result) throw new Error('Memory candidate export is missing.');
    campaigns.push({ play_style: style, accepted_choices: steps + baseline, status: preserved.status,
      pause_resume: true, checkpoint_branch_preserved: true, memory_candidate_exported: true });
  }
  console.log(JSON.stringify({ runtime: 'official installed DSH MCP client 0.2.0-rc.2',
    scope: 'isolated native tool registry; deterministic scripted choices; no LLM requests',
    discovered_tools: names.length, tool_calls: calls, scripted_recap_updates: recapUpdates, campaigns }, null, 2));
} finally {
  for (const fiber of fibers.reverse()) await fiber.dispose();
  if (scope) await scope.dispose();
}
