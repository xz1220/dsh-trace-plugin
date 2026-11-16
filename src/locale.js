import { zh } from '../vendor/dsh/packages/client/locale/src/locales/zh.ts';
import { en } from '../vendor/dsh/packages/client/locale/src/locales/en.ts';
import { ja } from '../vendor/dsh/packages/client/locale/src/locales/ja.ts';
import { es } from '../vendor/dsh/packages/client/locale/src/locales/es.ts';
import { fr } from '../vendor/dsh/packages/client/locale/src/locales/fr.ts';
import { de } from '../vendor/dsh/packages/client/locale/src/locales/de.ts';
import { ru } from '../vendor/dsh/packages/client/locale/src/locales/ru.ts';
import { pt } from '../vendor/dsh/packages/client/locale/src/locales/pt.ts';
import * as trajectory from '../vendor/dsh/packages/client/ui-trajectory/src/client/locales.ts';
import { codexLocales } from './locales/codex.js';
import { errorLocales } from './locales/errors.js';

const common = { zh, en, ja, es, fr, de, ru, pt };
const evidence = {
  zh: ['完整上下文', '原始请求', '原始响应'],
  en: ['Complete context', 'Raw request', 'Raw response'],
  ja: ['完全なコンテキスト', '元のリクエスト', '元のレスポンス'],
  es: ['Contexto completo', 'Solicitud original', 'Respuesta original'],
  fr: ['Contexte complet', 'Requête brute', 'Réponse brute'],
  de: ['Vollständiger Kontext', 'Rohe Anfrage', 'Rohe Antwort'],
  ru: ['Полный контекст', 'Исходный запрос', 'Исходный ответ'],
  pt: ['Contexto completo', 'Requisição original', 'Resposta original'],
};
export const supportedLocales = Object.keys(common);
export const normalizeLocale = (value) => {
  const language = typeof value === 'string' ? value.toLowerCase().split(/[-_]/)[0] : 'zh';
  return supportedLocales.includes(language) ? language : 'en';
};
export const dictionaries = Object.fromEntries(
  supportedLocales.map((locale) => [
    locale,
    {
      ...common[locale],
      ...trajectory[locale],
      ...(codexLocales[locale] || codexLocales.en),
      ...(errorLocales[locale] || errorLocales.en),
      'codex.prompt': evidence[locale][0],
      'codex.request': evidence[locale][1],
      'codex.response': evidence[locale][2],
    },
  ]),
);
export function translatorFor(value) {
  const locale = normalizeLocale(value),
    dictionary = dictionaries[locale];
  const t = (key, params = {}) =>
    String(dictionary[key] ?? dictionaries.en[key] ?? key).replace(
      /\{(\w+)\}/g,
      (_, name) => params[name] ?? '',
    );
  t.locale = locale;
  return t;
}
export const dictionary = dictionaries.zh;
export const t = translatorFor('zh');
