export const BASE_MESSAGES = [
  {id:'base', role:'developer', label:'基础指令', source:'model_instructions_file', text:'You are a coding assistant.\nUse the available tools to inspect the local workspace.\nReport only what you have verified.\nDo not modify files unless the user asks.'},
  {id:'developer', role:'developer', label:'开发者约束', source:'developer_instructions', text:'这是一次只读检查。\n仅执行用户指定的本地命令，不访问网络，不创建或修改文件。\n工具执行结束后，准确返回观察到的两行输出。'},
  {id:'workspace', role:'user', label:'工作区说明', source:'AGENTS.md', text:'# Workspace\n\n当前目录是一个用于验证轨迹查看器的示例工作区。\nfixture.txt 包含两行文本。请保留文件内容，不做任何修改。'},
  {id:'environment', role:'user', label:'运行环境', source:'environment_context', text:'工作目录：/workspace/trace-demo\n执行权限：只读\n终端：zsh\n语言：中文'},
  {id:'user', role:'user', label:'用户消息', source:'当前轮次', text:'读取 fixture.txt，然后原样返回文件里的两行内容。\n请使用一次终端工具调用完成，不要修改文件。'}
];
export const COMMAND = `python3 -c "from pathlib import Path; print(Path('fixture.txt').read_text(), end='')"`;
export const OUTPUT = 'TRACE_SAMPLE_READY\n42\n';
export const TOOL_SCHEMA = {name:'exec_command',description:'在当前工作区执行终端命令。',parameters:{type:'object',properties:{cmd:{type:'string'},yield_time_ms:{type:'integer',default:1000}},required:['cmd']}};
export const CALL_CODE = `const result = await tools.exec_command({\n  cmd: ${JSON.stringify(COMMAND)}\n});\ntext(result.output);`;
export const EVENTS = [
  {id:'user',kind:'user',label:'用户提交任务',summary:'读取 fixture.txt 并原样返回两行内容',start:0,end:0,seq:1},
  {id:'request-1',kind:'model',label:'模型请求 01',summary:'生成一次只读工具调用',start:0,end:3593,seq:2,input:1764,output:94,cache:1024},
  {id:'cell-1',kind:'cell',label:'代码单元 01',summary:'调用 exec_command 并返回结果',start:3862,end:3953,seq:3},
  {id:'tool-1',kind:'tool',label:'exec_command',summary:'读取 fixture.txt',start:3873,end:3950,seq:4,parent:'cell-1'},
  {id:'request-2',kind:'model',label:'模型请求 02',summary:'接收工具结果，生成最终回复',start:3989,end:5977,seq:5,input:1960,output:12,cache:1764,incremental:true},
  {id:'answer',kind:'assistant',label:'最终回复',summary:'TRACE_SAMPLE_READY · 42',start:5977,end:5977,seq:6}
];
export const KIND_LABEL = {model:'模型请求',tool:'工具调用',cell:'代码单元',user:'用户',assistant:'回复'};
export const SCENARIOS = [
 ['complete','正常回放'],['failure','工具失败'],['missing','缺少前序上下文'],['empty','尚未开启录制']
];
export function eventsFor(scenario) {
  const available=scenario==='missing'?EVENTS.filter(e=>['request-2','answer'].includes(e.id)):EVENTS;
  return available.map(e=>scenario==='failure' && e.id==='tool-1' ? {...e,failed:true,summary:'读取失败，文件不存在'} : scenario==='failure' && e.id==='answer' ? {...e,summary:'未找到文件，请确认路径'} : {...e});
}
export function messagesFor(id,scenario,mode) {
  if (id!=='request-2') return BASE_MESSAGES;
  const result={id:'result',role:'tool',label:'工具结果',source:'exec_command',text:scenario==='failure'?'FileNotFoundError: fixture.txt\nexit_code: 1':OUTPUT,inherited:false};
  if(mode==='delta'||scenario==='missing') return [result];
  return [...BASE_MESSAGES.map(m=>({...m,inherited:true})),{id:'call',role:'assistant',label:'工具调用',source:'模型请求 01',text:CALL_CODE,inherited:true},result];
}
export function rawRequest(id,scenario) {
  return {model:'gpt-6.1-sol',stream:true,...(id==='request-2'?{previous_response_id:'resp_demo_01'}:{}),input:messagesFor(id,scenario,id==='request-2'?'delta':'full').map(m=>({role:m.role,content:[{type:m.role==='tool'?'output_text':'input_text',text:m.text}]})),...(id==='request-1'?{tools:[TOOL_SCHEMA]}:{}),reasoning:{effort:'low'}};
}
export const JOURNEYS = {
 review: {label:'回看一次执行',intro:'先定位一次请求，再核对它看到的上下文和执行结果。',steps:[['开始录制','在启用了录制的 Codex 进程中运行任务。'],['打开轨迹','侧栏优先定位当前任务；也可选择已有录制。'],['定位请求','点击时间线中的模型请求，保留事件列表位置。'],['核对上下文','切换完整上下文与本次增量，逐条查看指令来源。'],['检查工具','查看原始参数、输出和终端结果，再回到时间线。']],scenario:'complete'},
 failure: {label:'定位一次失败',intro:'区分工具失败、模型失败与尚未完成，沿调用关系找到原因。',steps:[['发现失败','事件行保留失败状态、退出码和发生时间。'],['筛选失败','只显示失败事件，不隐藏它的调用关系。'],['读取原始结果','在详情中核对 stderr 和退出码。'],['回溯发起者','从工具返回代码单元或发起它的模型请求。'],['核对后续行为','确认模型是否看到了错误、是否重新执行。']],scenario:'failure'},
 missing: {label:'遇到数据缺口',intro:'明确告诉用户哪些证据缺失，不把增量请求误标为完整上下文。',steps:[['打开请求','当前请求引用了一条尚未载入的历史响应。'],['显示缺口','提示缺少前序请求，完整上下文暂不可用。'],['继续检查','本次增量、工具结果和已知时序仍可查看。'],['补充录制','用户补齐包含前序请求的 trace 文件。'],['重新关联','恢复上下文后标明来源，保留原始请求。']],scenario:'missing'}
};
