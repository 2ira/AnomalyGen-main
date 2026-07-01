import os


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