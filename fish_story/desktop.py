"""Double-click entry point; the CLI remains available for existing Agents."""
from __future__ import annotations

import sys


def main(argv=None):
    from .cli import main as cli_main
    args = list(sys.argv[1:] if argv is None else argv)
    double_click = not args
    if double_click:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8')
        print('大肥鱼的《底特律：变人》\n'
              '正在打开本机游戏页面；首次使用请在页面中准备 32 章剧情。\n'
              '请保持此窗口开启。关闭窗口会停止服务，已经保存的进度会保留。\n'
              '如果浏览器没有自动打开，请复制下方本机地址。\n', flush=True)
    try:
        result = cli_main(args or ['serve', '--open'])
    except KeyboardInterrupt:
        return 130
    except Exception:
        if not double_click:
            raise
        print('无法启动本机服务。请检查程序文件是否完整以及存档目录的读写权限。',
              file=sys.stderr, flush=True)
        result = 1
    if result not in (0, 130) and double_click:
        print('启动未完成。请保留当前文件夹中的 _internal，重新完整解压便携包。\n'
              '若文件夹不可写，请解压到自己的“下载”或“文档”目录后重试。\n'
              '存档保存在用户目录的 .fish-story-player，重新解压程序不会删除存档。',
              file=sys.stderr, flush=True)
        if sys.stdin and sys.stdin.isatty():
            try:
                input('按回车键关闭此窗口。')
            except (EOFError, KeyboardInterrupt):
                pass
    return result


if __name__ == '__main__':
    raise SystemExit(main())
