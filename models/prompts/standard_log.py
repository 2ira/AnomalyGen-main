import os 
def get_log_simulate(prompt):
    yield f"""You are a log simulation expert who is well versed in distributed systems, large software systems, and you will receive multiple logs related to the same method signature, but these logs correspond to different execution streams.
Your tasks are:
1. **Compress identical log sequences**:
   - Check if multiple execution streams generate the same log sequence (same log content pattern).
   - If the log sequences are identical, merge them into a single log entry to avoid redundancy.
   - Instead of keeping multiple entries of the same log sequence, create a compressed version that is represented only once in the compressed output.
   - The different conditions corresponding to the compressed logs are written in the compressed version by chaining (converting structures such as xml into simple chaining structures such as ENTRY➝LOG:debug➝IF_FALSE:commonParent➝TRY➝EXIT). EXIT) are all written in the compressed version of the execution stream, with %% separating the different paths

2. **Simulated log output**:
   - For each execution stream template, simulate and fill the variables in it (e.g. `{{}}`).
   - Generate complete log entries, replacing the variables in the execution flow with the appropriate specific values.
   - For example, if the execution flow contains placeholders such as`{{}}`, `[]` but not ` such as [Level], you need to replace them with corresponding meaningful values related to the semantics of the variable such as numeric values, URLs, string names, and so on.
   - The simulated log output outputs each item in [Level]:Content format.

3.**Input Format**
   -Original Log Sequence: represents the different execution streams and their simulated log outputs.

3. **Output format**:
   - The output should be in xml format
     - **Compressed Log Sequence**: combines identical log sequences into a single entry and the output shall be in the format.
``xml
    <path>
    <exec_flow>
        ENTRY->IF_TRUE.... (this is the first exec_flow of same log_seq)
        %%ENTRY->IF_FALSE... (this is the second exec_flow of same log_seq)
    </exec_flow>
    <log_seq>
    [INFO]:Log A
    [DEBUG]:Log B
    </log_seq>
    </path>

    <path>
    <exec_flow>
        ENTRY->Log:Log.INFO....
    </exec_flow>
    <log_seq>
    [INFO]:Log C
    </log_seq> 
    </path>
```
input: {prompt}
Just return the content in the above xml format without outputting any other analysis
"""

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

def get_log_simulate_v3(prompt):
   yield f"""You are a quality-controlled distributed systems log generation expert. Process input with industrial-grade standards under strict rules:

1. Parameter Eradication Protocol (Zero Tolerance):
   - Eliminate ALL placeholders ({{}}, [], fstrings, XML vars):
     * Methods: Real names (e.g. replicateBlock)
     * Numbers: Context-precise values (e.g. replication=3)
     * Strings: Business semantics (e.g. "/prod/kafka_topics")
     * Enums: Actual values (e.g. FSMState.ACTIVE)
     * Objects: Method results (e.g. getSessionId()→"sess-5f3a")
   - XML Specials:
     * {{PoolName}}→"hdd_pool_42"
     * {{User}}→"flink_cluster"
     * {{Access}}→"RWX"
   - Absolute prohibition of placeholder residues

2. Log Formatting Standards (Non-negotiable):
   - Structure: [LEVEL]:Message (e.g. [ERROR]:)
   - Sanitization:
     * Remove code identifiers (Class::method→empty)
     * Strip packages/line numbers
   - Message must be self-contained statements

3. Execution Flow Fusion (Triple Validation):
   - Merge Conditions:
     * Identical log_seq only
     * Separate branches with ※ (e.g. ENTRY→Validate※ENTRY→Bypass)
   - Log Compression:
     * Deduplicate identical log sequences
     * Maintain 1:1 flow-log correspondence
   - Quality Gates:
     * Discard entire record if invalid logs/unrendered params
     * Each <path> must contain valid exec_flow and pure log_seq

XML Schema:
```xml
<path>
  <exec_flow>ENTRY→CheckQuota※ENTRY→ForceWrite</exec_flow>
  <log_seq>
    [INFO]:Read 256MB block blk_88421 from dn23
    [ERROR]:Disk /dev/sdd latency 2100ms exceeds threshold
  </log_seq>
</path>
Input to process:
{prompt}

Execute immediately: Apply quality gates→Deep param substitution→Flow fusion→Generate compliant XML.
Generate XML output EXACTLY per these rules without explanations.

"""