"""Deterministic document-purpose tags, never a bag of words from the full body."""
import hashlib
import json
import re

VERSION='announcement-tags-v2-pi-review'
TAGS=[('shareholder','股东会'),('board','董事会'),('annual','年报'),('half_year','半年报'),('quarter','季报'),
      ('performance','业绩预告／快报'),('dividend','分红派息'),('proceeds','募集资金'),('shares','股份变动'),
      ('incentive','回购／股权激励'),('related','关联交易'),('guarantee','对外担保'),('investment','投资／资产交易'),
      ('treasury','理财／套期保值'),('governance','人员／公司治理'),('ipo','首次发行上市'),('refinancing','再融资'),
      ('risk','风险／监管'),('ir','投资者关系'),('audit','审计／持续督导'),('unclassified','待分类')]
FORMS=[('notice','通知'),('resolution','决议'),('legal','法律意见书'),('full','报告全文'),('summary','报告摘要'),
       ('correction','更正／修订'),('companion','配套文件'),('other','其他文件')]
COMMON=['shareholder','board','annual','half_year','quarter','dividend','proceeds']


def source_key(row):
    return hashlib.sha256(json.dumps([row.get('title'),row.get('document_sha256'),row.get('sha256')],ensure_ascii=False).encode()).hexdigest()


def classify_title(title):
    t=re.sub(r'\s+','',title);tags=[];forms=[]
    def add(tag):
        if tag not in tags:tags.append(tag)
    # Rules/bylaws and work reports describe governance, not a specific meeting.
    governance=bool(re.search(r'制度|章程|议事规则|细则|管理办法|运行情况说明|专门委员会.*设置|子公司.*简要情况|投资者关系管理.*安排|相关的承诺',t))
    meeting=bool(re.search(r'股东(?:大)?会',t)) and bool(re.search(r'通知|决议|法律意见|召开|取消|延期|议案|提案',t)) and not governance
    if meeting:add('shareholder')
    if re.search(r'董事会',t) and re.search(r'决议|会议通知|会议.*(?:取消|延期)|(?:取消|延期).*会议',t) and not governance:add('board')
    direct_report=re.search(r'\d{4}年(年度报告|度报告|半年度报告|第?[一三123]季度报告|[一三]季报)(?:摘要)?',t)
    companion=bool(re.search(r'审计|鉴证|审阅|核查|法律意见|保荐|持续督导|专项说明|述职|工作报告|履职',t))
    if direct_report and not companion:
        kind=direct_report[1];add('half_year' if '半年' in kind else 'annual' if kind in ('年度报告','度报告') else 'quarter')
        forms.append('summary' if '摘要' in t else 'full')
    patterns=[('performance',r'业绩(?:预告|快报|预增|预减|预亏|预盈)|扭亏'),('dividend',r'利润分配|权益分派|分红|派息|资本公积.*转增'),
        ('proceeds',r'募集资金|募投'),('shares',r'减持|增持|权益变动|限售.*(?:流通|解禁)|股份.*(?:质押|冻结)|解除.*限售'),
        ('incentive',r'回购|股权激励|股票期权|限制性股票|员工持股'),('related',r'关联交易|关联资金|非经营性资金占用'),
        ('guarantee',r'担保'),('investment',r'对外投资|增资|收购|重组|重大合同|资产(?:购买|出售|交易)|购买资产|出售资产'),
        ('treasury',r'现金管理|委托理财|套期保值|衍生品'),('governance',r'换届|选举|聘任|辞任|辞职|离任|离职|薪酬|工商变更|营业执照|注册资本|组织架构|独立董事.*(?:声明|承诺|独立性)|捐赠'),
        ('ipo',r'首次公开发行|招股|上市公告书|发行人.*发行上市|战略配售|发行结果|中签|网下发行'),
        ('refinancing',r'可转换.*债券|可转债|向特定对象|非公开发行|再融资|配股|增发'),
        ('risk',r'异常波动|诉讼|仲裁|处罚|问询|关注函|监管函|风险警示|停牌|复牌|退市|计提.*减值'),
        ('ir',r'业绩说明会|接待日|投资者.*(?:活动|说明会)'),('audit',r'审计报告|鉴证|审阅报告|持续督导|核查意见|核查报告|保荐书|专项说明|资金往来.*汇总表|内部控制评价|(?:聘任|续聘|更换).*会计师事务所')]
    if governance:
        add('governance')
    else:
        for tag,pattern in patterns:
            if re.search(pattern,t):add(tag)
    # An IPO document is not a refinancing document merely because it issues shares.
    if 'ipo' in tags and 'refinancing' in tags:tags.remove('refinancing')
    if re.search(r'年度.*(?:述职|工作报告|履职)|董事会.*独立性',t):add('governance')
    if meeting or 'board' in tags:
        if '法律意见' in t:forms.append('legal')
        elif '决议' in t:forms.append('resolution')
        elif re.search(r'通知|召开|延期|取消|提案|议案',t):forms.append('notice')
    elif '法律意见' in t:forms.append('legal')
    if re.search(r'更正|修订|修正',t):forms.append('correction')
    if companion and not meeting:forms.append('companion')
    return tags,forms or ['other']


def classify(row,document=None):
    key=source_key(row);manual=row.get('classification_override')
    if isinstance(manual,dict) and manual.get('source_key')==key:
        return {**manual,'status':'manual','version':VERSION}
    reviewed=row.get('classification_review')
    if isinstance(reviewed,dict) and reviewed.get('source_key')==key and reviewed.get('version')==VERSION:
        return {**reviewed,'requires_pi':False}
    tags,forms=classify_title(row.get('title',''));evidence={'field':'title','quote':row.get('title','')}
    # For an uninformative catalog title only, use the document's own first-page
    # heading. Stop before the guarantee/body; never classify from later mentions.
    generic=bool(re.fullmatch(r'(?:未知资料|资料附件|附件|公告|文件|document)(?:\d+)?(?:\.(?:pdf|docx))?',row.get('title',''),re.I))
    if not tags and generic and document:
        for page in document.get('pages',[])[:1]:
            prefix=re.split(r'本公司及|本公司董事会|本公司全体|正文|目录',page.get('text',''),maxsplit=1)[0]
            prefix=prefix[:600]
            found,detail=classify_title(prefix)
            if found:
                tags,forms=found,detail;evidence={'page':page.get('page',1),'anchor':f"page:{page.get('page',1)}",'quote':prefix};break
    return {'tags':tags or ['unclassified'],'forms':forms,'status':'pending_pi','requires_pi':True,
            'rule_confidence':None,'required_confidence':0.99,'confidence_basis':'uncalibrated_rules',
            'review_reason':'本地规则尚无99%准确率校准证据，必须由Pi复判；当前标签为候选',
            'version':VERSION,'source_key':key,'evidence':evidence,'manual_expired':bool(manual)}


def document_kind(title):
    """Coarse filing label for a company announcement title.

    Derived from the deterministic title rules above. It is an index label, not a
    legal conclusion, and never replaces profile or case-evidence checks.
    """
    tags,forms=classify_title(title)
    if 'ipo' in tags:return 'ipo'
    if 'governance' in tags and re.search(r'制度|章程|规则|细则|办法',title):return 'corporate_governance'
    if 'annual' in tags:return 'annual_report'
    if 'half_year' in tags:return 'half_year_report'
    if 'quarter' in tags:return 'quarter_report'
    if 'shareholder' in tags:
        if 'legal' in forms:return 'shareholder_legal_opinion'
        if 'resolution' in forms:return 'shareholder_resolution'
        return 'shareholder_notice'
    for pattern,kind in ((r'董事会.*决议','board_resolution'),(r'股东(?:大)?会.*通知','shareholder_notice'),
        (r'辞任|辞职|聘任|换届','management_change'),(r'关联交易|担保','related_transaction'),
        (r'诉讼|仲裁','litigation_arbitration'),(r'减持|权益变动','share_reduction'),(r'回购','repurchase'),
        (r'激励|员工持股','equity_incentive'),(r'可转换.*债券|可转债','refinancing_bond'),
        (r'发行股票','refinancing_equity'),(r'重大合同','major_contract'),(r'收购|重组','m_and_a'),(r'问询|关注函','inquiry_reply')):
        if re.search(pattern,title):return kind
    return 'unclassified'
