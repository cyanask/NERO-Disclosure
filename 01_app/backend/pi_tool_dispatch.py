"""Concurrent Pi tool transport; serialize mutations of one run, not read tools."""
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException

READ_TOOLS=frozenset(('read_event','search_library','read_library','read_attachment',
    'read_document','read_document_template','read_document_context',
    'knowledge_search','knowledge_read','knowledge_web_search','knowledge_download_read',
    'knowledge_history','knowledge_imports','knowledge_import_read'))


class ToolDispatch:
    def __init__(self, bridge, stop):
        self.bridge=bridge;self.stop=stop;self.closed=threading.Event()
        self.pool=ThreadPoolExecutor(thread_name_prefix='pi-tool')
        self.mutation_lock=threading.Lock();self.pending={}

    def submit(self,item):
        secrets=getattr(threading.current_thread(),'pi_secrets',())
        def invoke():
            threading.current_thread().pi_secrets=secrets
            def call():
                if self.closed.is_set() or self.stop.is_set():raise HTTPException(409,'执行已取消')
                return self.bridge(item['name'],item['args'])
            try:
                if item['name'] in READ_TOOLS:return call()
                # Writes still use the existing version/scope checks, and never
                # overlap another mutation of the same business run.
                with self.mutation_lock:return call()
            finally:threading.current_thread().pi_secrets=()
        self.pending[self.pool.submit(invoke)]=item

    def ready(self):
        for future,item in list(self.pending.items()):
            if future.done():
                del self.pending[future]
                yield item,future

    def close(self):
        self.closed.set()
        self.pool.shutdown(wait=True,cancel_futures=True)
