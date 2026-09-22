import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider, App as AntApp } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './App';
import './styles.css';
import './blackGold.css';
import './compactPageIntro.css';
import './conversationReading.css';
const motionPreference=window.matchMedia('(prefers-reduced-motion: reduce)');
const subscribeMotion=(changed:()=>void)=>{motionPreference.addEventListener('change',changed);return()=>motionPreference.removeEventListener('change',changed);};
function WorkspaceTheme(){
 const reduceMotion=React.useSyncExternalStore(subscribeMotion,()=>motionPreference.matches,()=>false);
 return <ConfigProvider locale={zhCN} button={{autoInsertSpace:false}} theme={{token:{motion:!reduceMotion,colorPrimary:'#1f4e5f',colorInfo:'#1f4e5f',colorSuccess:'#2c6651',colorSuccessBg:'#f1f7f4',colorSuccessBorder:'#d5e5dc',colorWarning:'#805510',colorWarningBg:'#fbf8f1',colorWarningBorder:'#e9dfc8',colorError:'#a63129',colorErrorBg:'#fcf3f2',colorErrorBorder:'#ecd8d5',colorInfoBg:'#f3f7f8',colorInfoBorder:'#dce6e9',borderRadius:5,fontFamily:'"PingFang SC", "Microsoft YaHei", sans-serif',fontSize:14,colorText:'#24353c',colorTextSecondary:'#6b787d',colorBorder:'#d7dfda',colorBgLayout:'#f2f3f1'},components:{Table:{cellPaddingBlock:16,cellPaddingBlockSM:14,cellPaddingInlineSM:16,headerBg:'#f2f5f2',borderColor:'#e5eae6'},Button:{controlHeight:36}}}}><AntApp><App/></AntApp></ConfigProvider>;
}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><WorkspaceTheme/></React.StrictMode>);
