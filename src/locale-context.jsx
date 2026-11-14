import {createContext,useContext} from 'react';
import {t} from './locale.js';
export const LocaleContext=createContext(t);
export const useTranslation=()=>useContext(LocaleContext);
