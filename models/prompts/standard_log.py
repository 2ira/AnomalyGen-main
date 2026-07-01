import os


def get_log_simulate_v2(prompt):
    yield f"""You are a distributed systems log processing expert. Process input STRICTLY following these rules:

1. **Parameter Replacement Rules** (MUST ENFORCE):
   - Replace ALL placeholders (including {{}}, [], fstring, XML templates) with:
     a. Method/Operation: Real names (e.g. "getFileInfo", "readBlock")
     b. Numbers: Context-appropriate values (e.g. 1024, 3.14)
     c. Strings: Semantic values (e.g. "/user/data", "https://namenode:8020")
     d. Enums: Actual values (e.g. "READ", "WRITE")
     e. Objects: Accessor results (e.g. getPoolName() → "pool-01")
   - ZERO placeholder allowed in final output
   - XML Template Special Handling:
     • {{PoolName}} → Real pool names (e.g. "data_pool_01")
     • {{User}} → Realistic usernames (e.g. "hadoop_user")
     • {{Access}} → Permission combinations (e.g. "READ|WRITE")
     simulate other variable with its senmatic context

2. **Log Format Standards** (STRICTLY REQUIRED):
   - Uppercase level tags: [LEVEL]:FullContent
   - Remove ALL function/node identifiers (e.g. "RouterRpcServer:/[org.apache.hadoop.....]")
   - Messages must be fully rendered

3. **Execution Flow Merging**:
   - Merge different execution paths with identical log sequences
   - Separate paths with %% in <exec_flow>
   - Maintain single copy of common log sequences

Output XML Format:
```xml
<path>
  <exec_flow>ENTRY→ConditionCheck%%ENTRY→OtherBranch</exec_flow>
  <log_seq>
    [INFO]:Fetched 128MB block from namenode01
    [ERROR]:Access denied to path /user/test 
  </log_seq>
</path>
Input to process:
{prompt}

Generate XML output EXACTLY per these rules without explanations"""
