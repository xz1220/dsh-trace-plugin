import {zh as common} from '../vendor/dsh/packages/client/locale/src/locales/zh.ts';
import {zh as trajectory} from '../vendor/dsh/packages/client/ui-trajectory/src/client/locales.ts';

export const dictionary={...common,...trajectory,
  'codex.prompt':'完整上下文','codex.request':'原始请求','codex.response':'原始响应',
  'record.rawResultUnavailable':'录制中没有原始结果',
  'timing.sessionTimestamps':'官方录制起止事件',
  'timing.sessionTimestampsRunning':'官方录制开始事件（运行中）',
};
export const t=(key,params={})=>String(dictionary[key]??key).replace(/\{(\w+)\}/g,(_,name)=>params[name]??'');
