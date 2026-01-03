import os
import argparse
from logparser.Drain import LogParser

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input_dir", type=str, required=True, help="包含 Zookeeper.log 的目录")
    ap.add_argument("--log_file", type=str, default="Zookeeper.log", help="日志文件名")
    ap.add_argument("--output_dir", type=str, required=True, help="Drain 输出目录（会生成 *_structured.csv）")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # 你的格式（注意：这里有两个空格，和 raw log 里 INFO 后面两个空格一致才行）
    log_format = r'<Date> <Time> - <Level>  \[<Node>:<Component>@<Id>\] - <Content>'

    # ✅ 这里必须是 List[str]，不能是 List[dict]
    # Drain 会把匹配到的内容统一替换成 "<*>"
    rex = [
        r'(/|)(\d+\.){3}\d+(:\d+)?',  # IP(:port)
        # 你如果还想 mask 数字/十六进制，也可以加：
        # r'0x[0-9a-fA-F]+',
        # r'(?<![A-Za-z])[-+]?\d+(?![A-Za-z])',
    ]

    st = 0.5
    depth = 4

    parser = LogParser(
        log_format=log_format,
        indir=args.input_dir,
        outdir=args.output_dir,
        depth=depth,
        st=st,
        rex=rex
    )

    parser.parse(args.log_file)

    structured_path = os.path.join(args.output_dir, args.log_file + "_structured.csv")
    print(f"[OK] Drain parsed. Structured CSV: {structured_path}")

if __name__ == "__main__":
    main()

"""
python parse_zookeeper.py \
  --input_dir dataset/Zookeeper \
  --log_file Zookeeper.log \
  --output_dir dataset/Zookeeper

"""