import pandas as pd, research_clay_vs_shadow as CS, inspect, re
C = pd.read_parquet("ctx_features.parquet"); print(list(C.columns))
src = inspect.getsource(CS.build_harness); print(sorted(set(re.findall(r'A\["(\w+)"\]', src)))); print(sorted(set(re.findall(r'F\["(\w+)"\]|"(\w+)":', src)))[:80])
