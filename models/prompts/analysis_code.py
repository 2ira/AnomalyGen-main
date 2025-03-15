import os

def get_java_parser_with_llm(source_code):
    return f"""
    You are an expert in code analysis, complete the following tasks based on the Java code snippet given below:
    1. Control Flow Analysis
        Parse all control flow structures in the code, including but not limited to:
        Method entry and exit
        Conditional statements (if/else)
        Loop structures (while, do-while, for)
        Exception handling (try/catch/finally)
        Synchronized blocks (synchronized)
        Branching (switch/case)
        Jump statements (break, continue, throw)
        Generate descriptive information for each control flow node, e.g. “ENTRY”, “IF: <condition>”, “THEN”, “ELSE”, “WHILE: <condition>”, “TRY”, “CATCH: <exception parameter>”, “FINALLY”, “SYNC”, etc. It is better to mark the same node type differently e.g. IF1,IF2
        Mark the source code location of logging calls (e.g. calls to LOG.debug, LOG.info, LOG.error, etc.) and display these logging calls in the call chain.
        Generate a complete call chain (call path) showing all possible paths from method entry to exit. For each path, nodes are connected using “->” to show the node order.
    2. Data Flow Analysis
        Analyze the data flow in the code and control flow and logging related variables.
        For each variable, indicate its definition and content (e.g. “Def: variableName before [IF2]”) and subsequent use (e.g. “Edge: variableName def before [IF: <condition>] -> use [FINALLY1]).
        If a variable is found to be undefined before use, this should also be flagged. The results of the analysis need to be conducive to the generation of log sequences.
    The control flow information obtained above (call chain, log call nodes) is integrated with the data flow information (dependency edges of variable definition and usage) to generate a comprehensive call chain description.
    The output should be clearly structured to facilitate subsequent merging and tracing of call information and logging sequences from individual nodes.
    Please output the results in a clear, hierarchical manner.
    Here is the Java code snippet to be analyzed: {source_code}

Output: Please return the various control flow, call and log related elements with unique representations and give all possible cfg flow directions
For example code:
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
You should return like below:
```xml
<elements>
    IF_NODE={{"IF1":"x>0"}}
    LOG_NODE={{
        "LOG1":"logging.debug("x is positive, x is{{}}",x);",
        "LOG2":"logging.info("Processing item");"
        }}
    FOR_NODE={{
        "FOR1":"start from 0 to 3"
    }}
    CALL_NODE = {{
        "CALL1":"processData();",
        "CALL2":"helperFunction();"
    }}
</elements>
<cfg>
<path1>ENTRY->IF1(False)->Exit</path1>
<path2>ENTRY->IF1(True)->LOG1->CALL1->FOR1(LOG2:3 times)->CALL2->Exit
</cfg>
```


The format template for the scope is:
```xml
<elements>
    NODE_kind = {{"kind_num":"content or condition",....}}
    else_kind = ....
</elements>
<cfg>
    <path1></path1>
    <path2><path2>
</cfg>
```
NOTE!!! Only the xml content in the above format needs to be output, no other information is needed and no interpretation is required.
"""
