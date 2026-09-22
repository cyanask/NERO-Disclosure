"""One macOS backend per login user, shared by desktop and command-line entrypoints."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

_active = None


def runtime_directory():
    return Path.home()/'Library/Application Support/NERO Disclosure Runtime'


class ServiceInstance:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.url = None
        self.owner = False
        self.lock = None
        self.state_path = runtime_directory()/'service.json'

    def publish(self, port):
        if not self.owner:return
        value = {'pid':os.getpid(), 'directory':str(self.directory), 'port':port}
        temporary = self.state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value))
        temporary.replace(self.state_path)

    def live_url(self):
        try:
            value = json.loads(self.state_path.read_text())
            if value['directory'] != str(self.directory):
                raise RuntimeError('NERO Disclosure 已使用另一资料目录运行，请先退出原服务；未启动第二个后端')
            port = int(value['port'])
            if not 1024 <= port <= 65535:return None
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):return None
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            url = f'http://127.0.0.1:{port}/'
            with opener.open(url+'api/chat/models', timeout=.5) as response:
                metadata = json.loads(response.read(500000))
            if isinstance(metadata, dict) and metadata.get('configuration_path') == str(self.directory/'pi-models.json'):return url
        except (OSError, ValueError, KeyError, TypeError):pass
        return None


@contextmanager
def service_instance(directory, timeout=60):
    global _active
    instance = ServiceInstance(directory)
    # This change governs the Mac product; Windows keeps its existing launcher.
    if sys.platform != 'darwin':
        yield instance
        return
    import fcntl
    base = runtime_directory()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = base/'service.lock'
    inherited = os.environ.pop('NERO_SERVICE_LOCK_FD', None)
    if inherited is not None:
        fd = int(inherited)
        actual, expected = os.fstat(fd), path.stat()
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise RuntimeError('服务重启锁不匹配，未启动')
        instance.lock = os.fdopen(fd, 'a+b')
        os.set_inheritable(fd, False)
    else:instance.lock = path.open('a+b')
    try:
        deadline = time.monotonic()+timeout
        while True:
            try:
                fcntl.flock(instance.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                instance.owner = True
                # Ignore a stale receipt once the kernel has released its owner.
                instance.state_path.unlink(missing_ok=True)
                break
            except BlockingIOError:
                instance.url = instance.live_url()
                if instance.url:break
                if time.monotonic() >= deadline:
                    raise RuntimeError('NERO Disclosure 已在启动或退出中，请稍候；未启动第二个后端')
                time.sleep(.1)
        if instance.owner:_active = instance
        yield instance
    finally:
        if instance.owner:
            instance.state_path.unlink(missing_ok=True)
            _active = None
        instance.lock.close()


def exec_restart(executable, command, env):
    """Keep the kernel lock across exec so a competing launcher cannot take over."""
    if _active is not None:
        fd = _active.lock.fileno()
        os.set_inheritable(fd, True)
        env = dict(env, NERO_SERVICE_LOCK_FD=str(fd))
    os.execve(executable, command, env)
