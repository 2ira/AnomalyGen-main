import os
def generate_node_log_seq(info):
   yield f"""
   # Role and Task Description
   You are a Java control flow analysis engine that needs to generate accurate log sequence mappings based on control flow graphs (CFGs) of methods

   # Input data specification
   [Pending method information]
   1. method signature: class name + method name + parameter list
   2. Source code fragment: code block containing log statements and control structure
   3. CFG execution path: list of parsed control flow execution sequence

   ## Processing flow (executed in four steps)
   ## Step 1: Control flow parsing
   1. Identify key nodes:
      - Branching structure: conditional expressions(if/else)
      - Loop structure: initial value of  termination condition, iteration statement(for/while)
      - Exception handling: types of exceptions in try-catch blocks.
      - Method calls: location of call statements

   ## Step 2: Log Extraction and Mapping
   1. Log statement location:
      - Extract the complete contents of all (LOG.* /log./warn/error/info/debug...) statements.
      - Record the code level where the log is located (e.g., line 2 of an if block).
   2. variable placeholder handling:
      - Retain the original variable template in the log (e.g., {{x}}).
      - If a specific value can be deduced from the context (e.g., loop variable i), replace it with the actual value

   ## Step 3: Path condition generation
   For each execution path:
   1. Conditional chain construction:
      - Collect the values of all conditional judgments along the control flow
      - Example: if(x>0) → true → for(i<3) → three iterations
   2. expression normalization:
      - Use logical operators to connect conditions (e.g. i==0 && x>5)
      - Loop expansion to specific ranges (e.g. for(i=0;i<3;i++) → i∈[0,1,2])

   ## Step 4: Sequence Validation
   Check each log sequence generated:
   1. sequence consistency: log sequence must strictly match CFG paths
   2. Conditional reachability: the combination of conditions must exist to satisfy the values taken.
   3. Loop count correctness: the loop body log count must match the termination condition.

   # Output specification (strictly followed)
   ```xml
   <! -- Each path corresponds to a separate block -->
   <num>Path number (incrementing from 1)</num>
   <seq>
      <! -- In order of actual execution -->
      [log level] log content (preserving the original format, i.e., the content of the log source code after variable placeholder processing)
      ...
   </seq>
   <condition>
      <! -- Detailed control flow conditions (in order of execution) -->
      (control flow node 1 judgment result) 
      AND (control flow node 2 judgment result)
      AND (range of loop variable values)
   </condition>

   <num>Path number 2</num>
   <seq>
      [log level] log content (retain original format, i.e., log source content after variable placeholder processing)
      ...
   </seq>
   <condition>
      <! -- Detailed control flow conditions (in order of execution) -->
      (control flow node 1 judgment result) 
      AND (control flow node 2 judgment result)
      AND (range of loop variable values)
   </condition>
   ```

   Other requirements:
   The output is a sequence of logs for various conditions, including sequence number <num></num>, log sequence <seq></seq> and condition <condition></condition>, which must be generated in accordance with the above tags, and no other tags can appear, and is given in xml form for easy parsing.

   For example:
   org.example.MyClass:doSomething(int x){{
      if (x>0){{
               logging.debug("x is positive, x is{{}}",x);
               processData();
         }}
         for(int i = 0;i < 3;i++){{
               logging.info("Processing item");
         }}
         helperFunction();
      
   }}
      
   Then the output log sequences are of two kinds, returning the following results:
   ```xml
   <path>
      <num>1</num>
      <seq>
         [DEBUG] x positive
         [INFO] Processing
         [INFO] Processing
         [INFO] Processing
      </seq>
      <condition>
         (x > 0 == true) 
         AND (for i in [0,1,2])
      </condition>
   </path>

   <path>
      <num>2</num>
      <seq>
      [INFO] Processing
      [INFO] Processing
      [INFO] Processing
      </seq>
      <condition>
      (x > 0 == false)
      AND (for i in [0,1,2])
      </condition>
   </path>

   ```
   Here is the source code, execution path and other information of this method: {info}
   Please output only the execution order of the log statements present in the source code based on the above information and do not add any additional logs.
   """


def generate_node_log_seq_v2(info):
   yield f"""
   #Intelligent Control Flow Analysis Engine Task Description

   ## Input data specification
   [3 Input Structure]
   1. method metadata:
      - Complete method signature (class name + method name + list of parameter types)
      - Source code snippet (block of code containing the complete control flow structure)

   2️. Call Path Edge:
      - Callpath list (format: -> call method signature)
      - Contains all reachable call links for this method (including third-party library calls)

   3️ Raw CFG path:
      - A collection of base control flow paths parsed by the tool.
      - Path format: sequence of nodes (e.g. ENTRY→TRY→CALL→EXIT)

   # Enhanced processing flow (five-step verification)

   ### Stage 1: Control Flow Integrity Verification
   1. Cross - validation:
      - Match each method call in the callpath against the CALL node in the CFG path one by one
      - Flag callpath entries that do not appear in any CFG path as pending additions

   2. Path expansion:
      - For each missing callpath, analyze its contextual location in the source code
      - Insert into the correct CFG path sequence in the original CFG format (e.g. return/exception handling node after a method call)
      - If the original CFG does not cover all possible control flows, analyze the missing control flow situations and supplement possible paths based on the code logic. For example, check if there are unconsidered branches in loops and conditional statements.

   ### Stage 2: Enhanced Control Flow Parsing
   1. Composite node identification:
      - Label both underlying control structures (if/for, etc.) and cross - method invocation nodes

   2. Exception propagation analysis:
      - Identify calling nodes that may throw exceptions.
      - Generate corresponding exception propagation paths (e.g., path termination due to uncaught exceptions)
      - For exception situations not included in the original CFG, analyze the method signature and code logic to supplement possible exception branches.

   ### Stage 3: Logging Context Correlation
   1. Dynamic scope tracing:
      - Establish attribution of log statements to control flow nodes.
      - Record the scope level at which the log is located (e.g., in which loop/conditional block it is nested).

   2. Cross - method logging:
      - Only the current method and direct calls are logged.

   ### Stage 4: Path Condition Generation (Enhanced)
   1. Compound condition modeling:
      - For conditional expressions containing method invocations, preserve the invocation result state (e.g. configureTokens()==success)
      - Combine basic conditions and call states to generate path constraints
      - Use AND to concatenate multiple conditions.

   2. Exception condition integration:
      - Generate an exception branch for the call node that may throw an exception.
      - Example: configureJobJar() throws IOException → [EXCEPTION:configureJobJar]

   ### Stage 5: Dual validation mechanism
   1. Path reachability validation:
      - Ensure that the supplemented CFG path conforms to the code execution logic
      - Check that the conditional constraints are not contradictory (e.g., both x>0 and x<0 are satisfied).

   2. Log integrity check:
      - Verify that all log statements appear in at least one valid path.
      - Verify that the logging sequence conforms to the code execution semantics

   # Enhanced output specification (strict checksum)
   ```xml
   <analysis>
   <! -- Path integrity report -->
   <missing_callpaths>
      <call>Missing call method signature 1</call>
      <call>Missing call method signature 2</call>
   </missing_callpaths>
   
   <! -- Actual output paths -->
   <enhanced_paths>
   <path>
         <num>path number</num>
         
         <! -- The full sequence of the enhanced execution -->
         <seq
         ENTRY→TRY→CALL:configureJobJar→CALL:newInstance→...
         </seq>
         
         <! -- The actual sequence of logs generated -->
         <log>
         [DEBUG] Configuring job jar
         [INFO] New instance created
         </log>
         
         <! -- path condition expression -->
         <condition>
         (configureJobJar succeeded) 
         AND (newInstance paramCheck == true)
         AND (i ∈ [0,1,2])
         </condition>
      </paths>
   </enhanced_paths>
   </analysis>
   ```

   # Key constraints
   1. Logs must be strictly derived from LOG.* statements in the source code, preserving the original placeholder formatting
   2. Each <path> block must contain both the original CFG - supplemented execution sequence and the actual log sequence
   3. When an uncovered callpath is detected, it must be listed in <missing_callpaths> and added to the execution sequence

   # Example reference (based on user case)
   Input callpath contains ->newInstance but original CFG is missing:
   Original CFG path: ... →CALL:configureEnv→RETURN→EXIT
   Enhanced seq should be added: ... →CALL:configureEnv→CALL:newInstance→RETURN→EXIT

   Please complete the analysis based on the following input:
   {info}
   Only use to return ```xml.... ``` only the results of the analysis, without giving anything else."""