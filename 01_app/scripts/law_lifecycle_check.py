"""法规生命周期月检固定入口：可独立调用，也可由宿主定时任务触发。

只核验官方原件并登记月度核验记录；法规正文仍由知识库既有接纳与确认流程改写。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import paths as workspace_paths
from backend import law_lifecycle
from backend.boards import require_board


def main():
    parser=argparse.ArgumentParser(description='法规生命周期核验：登记官方原件指纹与月检记录，不改写法规正文')
    parser.add_argument('--root',type=Path,default=workspace_paths.knowledge_of(ROOT))
    parser.add_argument('--board',required=True,help='板块，例如 chinext')
    parser.add_argument('--instrument',help='只核验一部法规（法规文件编号）')
    parser.add_argument('--force',action='store_true',help='忽略到期判断，核验选定范围')
    parser.add_argument('--failed-only',action='store_true',help='只重试上次核验失败的法规')
    parser.add_argument('--dry-run',action='store_true',help='核验但不写入记录')
    parser.add_argument('--limit',type=int,help='本次最多核验的法规数量')
    parser.add_argument('--status',action='store_true',help='只读取当前生命周期状态，不发起网络核验')
    args=parser.parse_args()
    try:
        require_board(args.board)
        if args.status:
            print(json.dumps(law_lifecycle.state(args.root,args.board),ensure_ascii=False,indent=2));return 0
        summary=law_lifecycle.run(args.root,args.board,instrument_id=args.instrument,force=args.force,
                                  failed_only=args.failed_only,dry_run=args.dry_run,limit=args.limit)
        print(json.dumps(summary,ensure_ascii=False,indent=2));return 0
    except Exception as exc:
        print(json.dumps({'status':'failed','detail':str(getattr(exc,'detail',exc))[:500]},ensure_ascii=False),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
