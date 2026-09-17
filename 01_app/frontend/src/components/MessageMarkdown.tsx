import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function MessageMarkdown({text}:{text:string}){
 return <div className="message-markdown"><Markdown remarkPlugins={[remarkGfm]} skipHtml
  components={{img:()=>null,a:({href,children})=><a href={href} target="_blank" rel="noreferrer">{children}</a>,
   table:({children})=><div className="message-table"><table>{children}</table></div>}}>{text}</Markdown></div>;
}
