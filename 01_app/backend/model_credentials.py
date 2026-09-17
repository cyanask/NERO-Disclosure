"""Project-scoped credentials in the OS vault; no plaintext credential files."""
import ctypes as C
import hashlib
import json
import os
import sys
from fastapi import HTTPException
from .paths import credential_scope


def credential_metadata(value):
    """Non-secret attributes for status reads; never include a key, token or env value."""
    return {'schema':1,'type':value.get('type','stored'),'env_keys':sorted((value.get('env') or {}).keys())}


def decode_metadata(text):
    try:
        value=json.loads(text or '')
        if value.get('schema')==1 and value.get('type') in ('api_key','oauth','revoked'):
            return {'type':value['type'],'env_keys':value.get('env_keys',[])}
    except (ValueError,TypeError,AttributeError):pass
    # Older keychain items have no metadata. Presence is not a connection test.
    return {'type':'stored','env_keys':None}


class ModelCredentialVault:
    def __init__(self, directory):
        scope=hashlib.sha256(str(credential_scope(directory)).encode()).hexdigest()[:24]
        self.service='com.nero.disclosure.pi.'+scope

    @property
    def available(self):return sys.platform=='darwin' or os.name=='nt'

    @property
    def label(self):return 'macOS 钥匙串' if sys.platform=='darwin' else 'Windows 凭据管理器' if os.name=='nt' else '当前系统暂不支持安全凭据库'

    def _operation(self, action, account, raw=None):
        try:
            if sys.platform=='darwin':return self._mac(action,account,raw)
            if os.name=='nt':return self._windows(action,account,raw)
            raise HTTPException(409,'当前系统未接入安全凭据库，请使用专用环境变量')
        except HTTPException:raise
        except Exception:raise HTTPException(409,'系统凭据库操作失败；未将凭据写入普通文件') from None

    def has(self, account):return bool(self._operation('has',account)) if self.available else False
    def status(self, account):
        return self._operation('status',account) if self.available else None
    def get(self, account):
        value=self._operation('get',account)
        if value is None:return None
        try:return json.loads(value)
        except (ValueError,UnicodeError):raise HTTPException(409,'当前凭据记录无法读取，请重新授权') from None
    def set(self, account, value):
        raw=json.dumps(value,separators=(',',':')).encode()
        if len(raw)>48000:raise HTTPException(422,'凭据超出安全存储上限')
        self._operation('set',account,raw)
    def delete(self, account):self._operation('delete',account)

    def _mac(self, action, account, raw):
        cf=C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        sec=C.CDLL('/System/Library/Frameworks/Security.framework/Security')
        cf.CFStringCreateWithCString.argtypes=[C.c_void_p,C.c_char_p,C.c_uint32];cf.CFStringCreateWithCString.restype=C.c_void_p
        cf.CFDataCreate.argtypes=[C.c_void_p,C.c_void_p,C.c_long];cf.CFDataCreate.restype=C.c_void_p
        cf.CFDictionaryCreate.argtypes=[C.c_void_p,C.POINTER(C.c_void_p),C.POINTER(C.c_void_p),C.c_long,C.c_void_p,C.c_void_p];cf.CFDictionaryCreate.restype=C.c_void_p
        cf.CFRelease.argtypes=[C.c_void_p]
        cf.CFDataGetLength.argtypes=[C.c_void_p];cf.CFDataGetLength.restype=C.c_long
        cf.CFDataGetBytePtr.argtypes=[C.c_void_p];cf.CFDataGetBytePtr.restype=C.c_void_p
        cf.CFDictionaryGetValue.argtypes=[C.c_void_p,C.c_void_p];cf.CFDictionaryGetValue.restype=C.c_void_p
        cf.CFStringGetCString.argtypes=[C.c_void_p,C.c_char_p,C.c_long,C.c_uint32];cf.CFStringGetCString.restype=C.c_bool
        sec.SecItemCopyMatching.argtypes=[C.c_void_p,C.POINTER(C.c_void_p)];sec.SecItemCopyMatching.restype=C.c_int32
        sec.SecItemAdd.argtypes=[C.c_void_p,C.c_void_p];sec.SecItemAdd.restype=C.c_int32
        sec.SecItemUpdate.argtypes=[C.c_void_p,C.c_void_p];sec.SecItemUpdate.restype=C.c_int32
        sec.SecItemDelete.argtypes=[C.c_void_p];sec.SecItemDelete.restype=C.c_int32
        refs=[]
        def constant(name):return C.c_void_p.in_dll(sec,name).value
        def string(value):
            ref=cf.CFStringCreateWithCString(None,value.encode(),0x08000100);refs.append(ref);return ref
        def dictionary(values):
            keys=(C.c_void_p*len(values))(*[constant(k) for k in values]);vals=(C.c_void_p*len(values))(*values.values())
            ref=cf.CFDictionaryCreate(None,keys,vals,len(values),None,None);refs.append(ref);return ref
        try:
            base={'kSecClass':constant('kSecClassGenericPassword'),'kSecAttrService':string(self.service),'kSecAttrAccount':string(account)}
            if action in ('get','has','status'):
                query={**base,'kSecMatchLimit':constant('kSecMatchLimitOne')}
                if action=='get':query['kSecReturnData']=C.c_void_p.in_dll(cf,'kCFBooleanTrue').value
                else:
                    # Background snapshots may inspect attributes, but must never show an auth UI.
                    query['kSecUseAuthenticationUI']=constant('kSecUseAuthenticationUIFail')
                    if action=='status':query['kSecReturnAttributes']=C.c_void_p.in_dll(cf,'kCFBooleanTrue').value
                result=C.c_void_p();status=sec.SecItemCopyMatching(dictionary(query),C.byref(result))
                if status==-25300:return None
                if status in (-25308,-25293) and action!='get':
                    return {'type':'locked','env_keys':None} if action=='status' else False
                if status:raise HTTPException(409,'无法读取系统凭据库，请检查钥匙串授权')
                try:
                    if action=='get':return C.string_at(cf.CFDataGetBytePtr(result),cf.CFDataGetLength(result))
                    if action=='has':return True
                    comment=cf.CFDictionaryGetValue(result,constant('kSecAttrComment'));buffer=C.create_string_buffer(2048)
                    text=buffer.value.decode('utf-8') if comment and cf.CFStringGetCString(comment,buffer,len(buffer),0x08000100) else ''
                    return decode_metadata(text)
                finally:
                    if result.value:cf.CFRelease(result)
            if action=='delete':status=sec.SecItemDelete(dictionary(base))
            else:
                data=cf.CFDataCreate(None,raw,len(raw));refs.append(data)
                attributes={'kSecValueData':data,'kSecAttrComment':string(json.dumps(credential_metadata(json.loads(raw))))}
                status=sec.SecItemAdd(dictionary({**base,**attributes}),None)
                if status==-25299:status=sec.SecItemUpdate(dictionary(base),dictionary(attributes))
            if status not in (0,-25300):raise HTTPException(409,'系统凭据库未完成保存，请检查钥匙串授权')
        finally:
            for ref in reversed(refs):
                if ref:cf.CFRelease(ref)

    def _windows(self, action, account, raw):
        from ctypes import wintypes as W
        class Credential(C.Structure):
            _fields_=[('Flags',W.DWORD),('Type',W.DWORD),('TargetName',W.LPWSTR),('Comment',W.LPWSTR),('LastWritten',W.FILETIME),('CredentialBlobSize',W.DWORD),('CredentialBlob',C.POINTER(C.c_byte)),('Persist',W.DWORD),('AttributeCount',W.DWORD),('Attributes',C.c_void_p),('TargetAlias',W.LPWSTR),('UserName',W.LPWSTR)]
        lib=C.WinDLL('Advapi32.dll',use_last_error=True);target=self.service+':'+account
        lib.CredReadW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.POINTER(C.POINTER(Credential))];lib.CredReadW.restype=W.BOOL
        lib.CredWriteW.argtypes=[C.POINTER(Credential),W.DWORD];lib.CredWriteW.restype=W.BOOL
        lib.CredDeleteW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD];lib.CredDeleteW.restype=W.BOOL
        lib.CredFree.argtypes=[C.c_void_p]
        if action in ('get','has','status'):
            ptr=C.POINTER(Credential)()
            if not lib.CredReadW(target,1,0,C.byref(ptr)):
                if C.get_last_error()==1168:return None
                raise HTTPException(409,'无法读取 Windows 凭据管理器')
            try:
                if action=='status':return decode_metadata(ptr.contents.Comment)
                return C.string_at(ptr.contents.CredentialBlob,ptr.contents.CredentialBlobSize) if action=='get' else True
            finally:lib.CredFree(ptr)
        if action=='delete':ok=lib.CredDeleteW(target,1,0)
        else:
            if len(raw)>2560:raise HTTPException(409,'此凭据超出 Windows 通用凭据大小上限；请使用 API Key 方式')
            buffer=(C.c_byte*len(raw)).from_buffer_copy(raw)
            entry=Credential(Type=1,TargetName=target,Comment=json.dumps(credential_metadata(json.loads(raw))),CredentialBlobSize=len(raw),CredentialBlob=buffer,Persist=2,UserName=account)
            ok=lib.CredWriteW(C.byref(entry),0)
        if not ok and not(action=='delete' and C.get_last_error()==1168):raise HTTPException(409,'Windows 凭据管理器操作失败')
