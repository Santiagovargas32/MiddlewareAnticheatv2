"""Manage only the two dedicated local binaries, with PID instance validation."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time


@contextmanager
def runtime_lock(directory):
    import fcntl
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError('runtime directory must be owned by the current user with mode 0700')
    fd=os.open(directory/'lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally: os.close(fd)


def identity(pid):
    try:
        status=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return dict(pid=pid,start_ticks=status[19],executable=str(Path(f'/proc/{pid}/exe').resolve(strict=True)))
    except (OSError,ValueError,IndexError): return None


def matches(record):
    return identity(record['pid'])=={key:record[key] for key in ('pid','start_ticks','executable')}


def stop_process(record):
    if not matches(record): return
    # Hold the kernel PID reference while checking identity and sending signals.
    fd=os.pidfd_open(record['pid'])
    try:
        if not matches(record): return
        signal.pidfd_send_signal(fd,signal.SIGTERM)
        deadline=time.monotonic()+2
        while matches(record) and time.monotonic()<deadline: time.sleep(0.01)
        if matches(record):
            signal.pidfd_send_signal(fd,signal.SIGKILL)
            deadline=time.monotonic()+2
            while matches(record) and time.monotonic()<deadline: time.sleep(0.01)
            if matches(record): raise ValueError('process_stop_timeout')
    except ProcessLookupError: pass
    finally: os.close(fd)


def load(directory):
    path=directory/'state.json'
    if not path.exists(): return []
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as file:
        state=json.load(file)
    if not isinstance(state,list) or len(state)>2: raise ValueError('invalid_state')
    for item in state:
        if item.get('name') not in ('lab_server','lab_adapter') or not isinstance(item.get('pid'),int) or item['pid']<=1:
            raise ValueError('invalid_state')
    return state


def save(directory,records):
    fd=os.open(directory/'state.new',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as file: json.dump(records,file);file.write('\n')
        os.replace(directory/'state.new',directory/'state.json')
    finally:
        (directory/'state.new').unlink(missing_ok=True)


def spawn(binary,arguments,port,directory):
    fd=os.open(directory/(binary.name+'.log'),os.O_CREAT|os.O_TRUNC|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w+') as log:
        process=subprocess.Popen([str(binary),*arguments],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        try:
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                log.seek(0);line=log.readline()
                if line.endswith('\n'):
                    boot=json.loads(line)
                    if boot.get('ev')!='boot' or boot.get('port')!=port: raise ValueError('invalid_readiness')
                    record=identity(process.pid)
                    if record is None: raise ValueError('process_exited')
                    return dict(record,name=binary.name,port=port)
                if process.poll() is not None: raise ValueError('process_start_failed')
                time.sleep(0.01)
            raise ValueError('readiness_timeout')
        except BaseException:
            if process.poll() is None: process.terminate()
            try: process.wait(timeout=2)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=2)
            raise


def manage(args):
    if not hasattr(os,'pidfd_open'): raise ValueError('local process management requires Linux pidfd support')
    directory=args.runtime.resolve()
    with runtime_lock(directory):
        records=load(directory)
        status=[dict(record,running=matches(record)) for record in records]
        if args.command=='status':
            print(json.dumps(dict(running=len(status)==2 and all(r['running'] for r in status),processes=status)))
            return
        if args.command=='stop':
            for record in reversed(records): stop_process(record)
            save(directory,[]);print(json.dumps(dict(stopped=True)));return
        if records and any(item['running'] for item in status):
            if len(records)==2 and all(item['running'] for item in status):
                print(json.dumps(dict(running=True,processes=status)));return
            raise ValueError('partial service: run stop before start')
        started=[]
        try:
            build=args.build.resolve()
            started.append(spawn(build/'lab_server',['--port',str(args.port),'--request-ms','10000','--timeout-ms','15000','-v'],args.port,directory))
            started.append(spawn(build/'lab_adapter',['--listen',f'127.0.0.1:{args.adapter_port}','--upstream',f'127.0.0.1:{args.port}','-v'],args.adapter_port,directory))
            save(directory,started)
        except BaseException:
            for record in reversed(started): stop_process(record)
            raise
        print(json.dumps(dict(running=True,processes=started)))
