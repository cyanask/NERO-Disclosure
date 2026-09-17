"""Disclosure-matter kinds and their fact fields.

Leaf constant module: domain, library and workflow all need these labels; keeping
them here lets those modules share one definition without importing each other.
"""

KINDS = {
    'board_resolution': ('董事会决议', [('meeting_date','会议日期','date'),('resolution_subject','决议事项','text'),('passed','是否通过','boolean'),('requires_shareholder_approval','是否须股东会审议','boolean'),('contains_disclosable_information','是否涉及应披露重大信息','boolean')]),
    'shareholder_notice': ('股东会通知', [('meeting_date','会议日期','date'),('meeting_method','会议方式','text'),('agenda','会议议程','text'),('meeting_type','会议类型（annual/extraordinary）','text')]),
    'management_change': ('董高人员变动', [('person_name','人员姓名','text'),('position','职务','text'),('change_type','变动类型','text'),('effective_date','生效日期','date')]),
    'related_transaction': ('关联交易', [('amount','交易金额（元）','number'),('audited_net_assets','最近一期经审计净资产（元）','number'),('audited_total_assets','最近一期经审计总资产（元）','number'),('counterparty','交易对方','text'),('is_related_party','是否关联方','boolean'),('counterparty_type','关联方类型（natural_person/legal_person）','text'),('is_guarantee','是否担保','boolean'),('daily_expected','是否日常交易预计','boolean'),('exemption_claimed','是否主张豁免','boolean'),('cumulative_amount','累计金额（元）','number')]),
    'litigation_arbitration': ('诉讼仲裁', [('amount','涉案金额（元）','number'),('audited_net_assets','最近一期经审计净资产（元）','number'),('case_stage','案件阶段','text'),('cumulative_amount','累计金额（元）','number'),('material_impact','是否重大影响','boolean'),('resolution_validity_case','是否涉及决议效力','boolean')]),
}
