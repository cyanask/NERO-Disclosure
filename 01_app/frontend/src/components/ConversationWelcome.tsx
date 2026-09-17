const starters=[
 {title:'判断是否需要披露',example:'这件事需要履行什么程序、披露什么？',prompt:'公司准备办理以下事项，请判断需要履行的程序和披露要求：\n'},
 {title:'查法规和类似公告',example:'查找适用规则和可参考的公告案例。',prompt:'请帮我查找以下事项的适用规则和类似公告：\n'},
 {title:'起草公告',example:'根据已知情况，先形成一份公告工作稿。',prompt:'请根据以下已知情况起草公告，缺失信息请具体标注待补：\n'},
 {title:'修改文稿或制作 Word',example:'说明要修改的内容，或要制成 Word 的文稿。',prompt:'我想修改文稿或制作 Word，具体对象和要求如下：\n'},
 {title:'更新与编辑知识库',example:'历史公告库、法规库、案例库、黑名单库、模板库。',prompt:'请帮我更新或编辑知识库，目标资料、来源和修改要求如下：\n'},
];

/** Examples only prepare an editable message; they never select a runtime mode. */
export default function ConversationWelcome({disabled,onStart}:{disabled:boolean;onStart:(prompt:string)=>void}){
 return <section className="conversation-welcome" aria-label="会话能力与示例">
  <h3>这段会话可以帮你做什么</h3>
  <p>咨询信披问题、查找法规和公告案例、起草或修改公告，以及制作 Word；也可以更新、编辑下列知识库。</p>
  <div className="conversation-starters">
   {starters.map(item=><button type="button" key={item.title} disabled={disabled} onClick={()=>onStart(item.prompt)}>
    <strong>{item.title}</strong><span>{item.example}</span>
   </button>)}
  </div>
  <p>直接说明想完成的工作和已知情况即可。资料不全也可以开始，我会提示关键缺口和合适的下一步。</p>
  <p className="starter-hint">点击示例填入输入框，补充后发送；也可以直接输入自己的需求。</p>
 </section>;
}
