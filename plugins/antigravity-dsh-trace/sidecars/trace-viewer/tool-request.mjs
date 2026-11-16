// Only the viewer's read APIs cross the sidecar boundary. The data provider
// receives the pane's native conversation identity on every request.
export const VIEWER_TOOLS = new Set([
  'list_rollout_traces', 'show_rollout_trace', 'open_rollout_viewer',
  'get_rollout_binding', 'get_rollout_overview', 'get_rollout_delta',
  'get_rollout_detail', 'get_rollout_record', 'get_rollout_projection',
  'get_rollout_cell_detail', 'read_rollout_cell_text', 'get_rollout_request_info',
  'search_rollout_cells', 'read_rollout_text',
]);

const CONVERSATION_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

export function makeToolRequest(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || !VIEWER_TOOLS.has(data.name)) {
    throw new Error('Unsupported viewer operation.');
  }
  const conversationId = data.conversationId;
  if (typeof conversationId !== 'string' || !CONVERSATION_ID.test(conversationId)) {
    throw new Error('Open DSH Trace from a conversation to view its execution trace.');
  }
  const args = data.arguments ?? {};
  if (!args || typeof args !== 'object' || Array.isArray(args) || JSON.stringify(args).length > 1024 * 1024) {
    throw new Error('Invalid viewer arguments.');
  }
  if (args.threadId !== undefined && args.threadId !== conversationId) {
    throw new Error('The requested conversation does not belong to this pane.');
  }
  if (args.traceId !== undefined && args.traceId !== `native:${conversationId}`) {
    throw new Error('The requested trace does not belong to this pane.');
  }
  return {
    name: data.name,
    arguments: args,
    _meta: {host: 'antigravity', conversationId},
  };
}
