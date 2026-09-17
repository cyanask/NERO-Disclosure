from backend.research_session import ResearchSession


def test_reuses_same_version_but_reloads_changed_bytes():
 cache=ResearchSession();calls=[]
 def load():calls.append(1);return {'id':'law','text':'完整当前原文'}
 assert cache.read('read_library',{'item_id':'law'},'v1',load)['text']=='完整当前原文'
 assert cache.read('read_library',{'item_id':'law'},'v1',load)['cache_hit']
 assert len(calls)==1
 cache.read('read_library',{'item_id':'law'},'v2',load);assert len(calls)==2


def test_no_evidence_hint_does_not_block_later_search():
 cache=ResearchSession();calls=[]
 def empty():calls.append(1);return {'items':[]}
 for i in range(3):cache.read('search_library',{'query':str(i)},'v1',empty)
 assert cache.read('search_library',{'query':'fourth'},'v1',empty)['research_notice']
 assert len(calls)==4
 found=cache.read('search_library',{'query':'new topic'},'v1',lambda:{'items':[{'id':'new law'}]})
 assert found['items']==[{'id':'new law'}] and not found.get('search_paused')
 cache.read('search_library',{'query':'','view':'groups'},'v1',lambda:{'items':[{'id':'instrument'}]})
 assert not cache.read('search_library',{'query':'条款'},'v1',empty).get('search_paused')
 assert cache.stats['suppressed_searches']==0


def test_directory_fallback_is_not_new_evidence():
 cache=ResearchSession()
 for i in range(3):cache.read('knowledge_web_search',{'query':str(i)},'v1',lambda:{'items':[{'url':'https://official.invalid/directory'}],'coverage':'目录入口，不是匹配法规或案例'})
 assert cache.streak==3
 result=cache.read('knowledge_web_search',{'query':'again'},'v1',lambda:{'items':[{'url':'https://official.invalid/law'}]})
 assert result['items'][0]['url'].endswith('/law') and cache.streak==0
