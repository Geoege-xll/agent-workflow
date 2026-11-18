"""仅供仓库发布及安装验收使用，以单个只读 Git 进程逐项读取已提交的文件树。"""

from contextlib import contextmanager
import re
import subprocess
import threading


@contextmanager
def tree_blobs(repository, revision, *, env=None, timeout=180):
    # ls-tree 只保留元数据，文件内容经持久管道逐项读取。逐项发请求再取回应，
    # 避免一次写入全部 OID 时与已满的 stdout 管道相互等待。
    git = ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repository)]
    listing = subprocess.check_output([*git, "ls-tree", "-r", "-l", "-z", revision],
                                      stderr=subprocess.PIPE, env=env, timeout=timeout)
    with subprocess.Popen([*git, "cat-file", "--batch"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as process:
        def entries():
            for entry in listing.split(b"\0"):
                if not entry:
                    continue
                header, raw_name = entry.split(b"\t", 1)
                mode, kind, oid, size = header.split()
                name = raw_name.decode("utf-8")
                if kind != b"blob" or mode not in {b"100644", b"100755"}:
                    raise ValueError("Git 树含非普通文件：" + name)
                if not re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid) or not size.isdigit():
                    raise ValueError("Git 树含无效对象标识或大小：" + name)
                process.stdin.write(oid + b"\n")
                process.stdin.flush()
                # 对照树中的 OID、类型和长度检查回复；内容可含换行或空字节，
                # 因此只按已确认长度读正文，再单独消费协议规定的换行。
                if process.stdout.readline(128) != oid + b" blob " + size + b"\n":
                    raise ValueError("Git 对象标识、类型或长度与文件树不一致：" + name)
                length = int(size)
                body = process.stdout.read(length)
                if len(body) != length or process.stdout.read(1) != b"\n":
                    raise ValueError("Git 对象内容或帧结束符不完整：" + name)
                yield name, mode.decode("ascii"), body

        # 普通管道 read 可能阻塞，超时由独立定时器终止本进程，使读端收到 EOF。
        # 消费者拒绝某个文件或抛出异常时也必须回收进程，不能残留等待下一请求的 Git。
        timer = threading.Timer(timeout, process.kill)
        timer.start()
        try:
            yield entries()
            process.stdin.close()
            if process.stdout.read(1) or process.wait() != 0:
                raise ValueError("Git 批量对象读取未正常结束")
        finally:
            timer.cancel()
            timer.join()
            if process.poll() is None:
                process.kill()
