"""Version-bound reuse and advisory feedback; research calls are not capped."""
import copy,json

class ResearchSession:
    def __init__(self):self.version=None;self.cache={};self.seen=set();self.streak=0;self.stats={'searches':0,'empty_searches':0,'cache_hits':0,'suppressed_searches':0}

    def read(self,name,args,version,call):
        if version!=self.version:self.version=version;self.cache={};self.seen=set();self.streak=0
        search='search' in name;key=json.dumps([name,args],sort_keys=True,ensure_ascii=False)
        if key in self.cache:
            self.stats['cache_hits']+=1
            return {**copy.deepcopy(self.cache[key]),'cache_hit':True,'reuse_notice':'复用本轮同一资料版本的已读结果，不代表新增证据。'}
        result=call()
        if search:
            self.stats['searches']+=1
            items=result.get('items',[]) if isinstance(result,dict) else []
            identities={str(x.get('id') or x.get('url')) for x in items if x.get('id') or x.get('url')}
            # Official navigation fallback is not matched evidence.
            if '不是匹配法规' in str(result.get('coverage','')):identities=set()
            if not identities:self.stats['empty_searches']+=1
            new=identities-self.seen;self.seen|=identities;self.streak=0 if new else self.streak+1
            if self.streak>=3:
                result={**result,'research_notice':'连续检索尚无新增证据。可改用条款、分组或已有来源定位；当前结果已如实返回，仍可继续查询。'}
        else:self.streak=0
        if isinstance(result,dict):self.cache[key]=copy.deepcopy(result)
        return result
