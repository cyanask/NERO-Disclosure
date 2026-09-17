"""Bounded Node model-control protocol: catalog, login, resolve and probe."""
import queue
import json
import threading
from fastapi import HTTPException
from . import pi_subprocess


def command(code_root,packet,timeout=15,process_hook=None,event_hook=None,input_hook=None):
    session=pi_subprocess.Session([pi_subprocess.node_path(),code_root/'runtime/pi/model_control.mjs'],code_root/'runtime/pi')
    process=session.process
    if process_hook:process_hook(process)
    if input_hook:input_hook(session.send)
    timer=threading.Timer(timeout,session.terminate);timer.daemon=True;timer.start();result=None;size=0
    try:
        session.send(packet)
        while True:
            try:line=session.read()
            except queue.Empty:continue
            if line is None:break
            size+=len(line)
            if size>3000000:raise HTTPException(409,'Pi 模型操作输出超出上限')
            value=json.loads(line)
            if value.get('type')=='result':result=value['result']
            elif value.get('type') in ('device_code','auth_url','auth_prompt','auth_prompt_cancelled') and event_hook:event_hook(value)
            elif value.get('type')=='error':raise HTTPException(409,'Pi 未完成操作，请核对网络、授权与模型设置')
        session.wait()
        if result is None or session.returncode:raise HTTPException(409,'Pi 模型操作未完成，未记录成功')
        return result
    finally:
        timer.cancel()
        session.close()
