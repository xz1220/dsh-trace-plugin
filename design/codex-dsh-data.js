import {BASE_MESSAGES,COMMAND,OUTPUT,CALL_CODE,TOOL_SCHEMA} from './data.js';
export {BASE_MESSAGES,COMMAND,OUTPUT,CALL_CODE,TOOL_SCHEMA};
export const EXEC_SCHEMA={type:'custom',name:'functions.exec',description:'运行 JavaScript 代码以编排工具调用。',format:{type:'text'}};
export const REQUESTS=[
 {id:'req1',number:1,start:0,end:3593,label:'请求 #1',model:'gpt-6.1-sol',input:1764,cached:1024,output:94,responseId:'resp_demo_01',payload:'payloads/4.json',mode:'完整请求'},
 {id:'req2',number:2,start:3989,end:5977,label:'请求 #2',model:'gpt-6.1-sol',input:1960,cached:1764,output:12,responseId:'resp_demo_02',previous:'resp_demo_01',payload:'payloads/12.json',mode:'增量请求'}
];
export const RECORDS=[
 {id:'system',index:1,kind:'system',title:'基础指令与开发者约束',text:'已加载基础指令、开发者约束与工具声明',start:0,end:0,request:'req1'},
 {id:'user',index:2,kind:'user',title:'用户消息',text:'读取 fixture.txt，并原样返回两行内容。',start:0,end:0,request:'req1',turnStart:true},
 {id:'workspace',index:3,kind:'context',title:'工作区上下文',text:'AGENTS.md · 只读工作区 · /workspace/trace-demo',start:0,end:0,request:'req1'},
 {id:'assistant1',index:4,kind:'message',title:'助手 · 请求 #1',text:'调用 functions.exec 读取本地文件',start:0,end:3593,request:'req1',boundary:'req1'},
 {id:'cell',index:5,kind:'tool',title:'functions.exec',text:'运行只读文件检查',args:'读取并输出 fixture.txt',result:'TRACE_SAMPLE_READY · 42',start:3862,end:3953,request:'req1',parent:'assistant1'},
 {id:'exec',index:6,kind:'subtool',title:'exec_command',text:'读取 fixture.txt',args:COMMAND,result:'TRACE_SAMPLE_READY · 42',start:3873,end:3950,request:'req1',parent:'cell'},
 {id:'assistant2',index:7,kind:'message',title:'助手 · 请求 #2',text:'TRACE_SAMPLE_READY · 42',start:3989,end:5977,request:'req2',boundary:'req2'}
];
export const SCENARIOS=[['complete','正常回放'],['failure','工具失败'],['missing','上下文不完整'],['empty','未开启录制']];
export const KIND_NAMES={system:'系统',user:'用户',context:'上下文',message:'助手',tool:'工具',subtool:'子工具'};
export function recordsFor(scenario){
 const rows=scenario==='missing'?RECORDS.filter(r=>r.request==='req2'):RECORDS;
 return rows.map(r=>scenario==='failure'&&r.id==='exec'?{...r,error:true,result:'FileNotFoundError · exit 1'}:scenario==='failure'&&r.id==='cell'?{...r,result:'收到工具错误，返回结果'}:scenario==='failure'&&r.id==='assistant2'?{...r,text:'未找到 fixture.txt，请确认路径。'}:{...r});
}
export function outputFor(scenario){return scenario==='failure'?'Traceback (most recent call last):\n  File "<string>", line 1\nFileNotFoundError: fixture.txt\n':OUTPUT;}
export function contextFor(requestId,scenario,mode='full'){
 if(requestId==='req1')return BASE_MESSAGES;
 const result={id:'result',role:'tool',label:'工具返回值',source:'functions.exec · 本次发送',text:outputFor(scenario),type:'custom_tool_call_output',callId:'call_exec_01'};
 if(mode==='delta'||scenario==='missing')return [result];
 return [...BASE_MESSAGES.map(m=>({...m,inherited:true})),{id:'call',role:'assistant',label:'助手工具调用',source:'请求 #1 的输出',text:CALL_CODE,type:'custom_tool_call',inherited:true},result];
}
export function requestPayload(requestId,scenario){
 const common={model:'gpt-6.1-sol',stream:true,tool_choice:'auto',reasoning:{effort:'low'},store:false};
 if(requestId==='req2')return {type:'response.create',...common,previous_response_id:'resp_demo_01',input:[{type:'custom_tool_call_output',call_id:'call_exec_01',output:outputFor(scenario)}]};
 return {...common,input:[{type:'additional_tools',role:'developer',tools:[EXEC_SCHEMA,TOOL_SCHEMA]},...BASE_MESSAGES.map(m=>({type:'message',role:m.role,content:[{type:'input_text',text:m.text}]}))]};
}
export function textFor(record,scenario){
 if(record.id==='system')return BASE_MESSAGES.slice(0,2).map(m=>`[${m.label}]\n${m.text}`).join('\n\n');
 if(record.id==='user')return BASE_MESSAGES.find(m=>m.id==='user').text;
 if(record.id==='workspace')return BASE_MESSAGES.filter(m=>['workspace','environment'].includes(m.id)).map(m=>`[${m.label}]\n${m.text}`).join('\n\n');
 if(record.id==='cell'||record.id==='assistant1')return CALL_CODE;
 return outputFor(scenario);
}
