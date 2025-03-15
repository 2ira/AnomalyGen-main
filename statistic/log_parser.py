

from logparser.Drain import LogParser

log_format = r'<Level>:<Content>'
input_dir = 'output/log_events/'
output_dir = 'output/log_events/'
log_file = 'dfs_simple_log_events.log'
regex = [
    r'(/|)([0-9]+\.){3}[0-9]+(:[0-9]+|)(:|)',  
    r'\{.*?\}'  
]

st = 0.5
depth = 4

parser = LogParser(log_format, indir=input_dir, outdir=output_dir, depth=depth, st=st, rex=regex)
parser.parse(log_file)

print(f"finish parsing,results are saved to {output_dir} ")