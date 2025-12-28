# AnomalyGen: An Automated Semantic Log Sequence Generation Framework with LLM for Anomaly Detection
AnomalyGen is the first automatic log generation framework that incorporates large language modeling. The framework is to utilize enhanced program analysis as well as the LLM chain of thought to collaboratively iterate through log generation without dynamically executing logs. 

Specifically, AnomalyGen consists of the following four core phases:
- PHASE I: Logging-related call graph pruning
- PHASE II: Fine-grained Subgraph Mining and Control Flow Diagram Enhancement
- PHASE III:  Recursive Log Merging with CoT Inference Verification
- PHASE IV:Knowledge-Driven Exception Log Labeling

## Project Structure
The project directory is organized as follows:

```
AnomalyGen-main/
├── hadoop [Project directory to be analyzed]
├── java-callgraph2
│   ├── jar-output_dir
│   │   └── _javacg2_config/
│   │       └── config.properties  # Main configuration file
│   └── [Tool to generate global call graphs]
├── java-parser
│   ├── JavaParserServer.java  # Generates single node log-related CFG
│   └── MethodExtractorGateway.java  # Maps signatures to source code
├── main
│   ├── venv  # Python virtual environment for the project(created by build_env.sh)
│   ├── auto_callgraph_config.py  # Collects class files and configures java-callgraph2
│   ├── auto_run.py  # Main execution script
│   ├── auto_global_callgraph_generation.py  # Automatically config the compile setting,generate global callgraph, prune for the log-related node.
│   ├── auto_run_ablation_v1.py  # Ablation data generation script, which is without cot
│   ├── auto_run_ablation_v2.py  # Ablation data generation script, which is without analysis
|   ├── auto_prepare.py  # Store global call path script
│   ├── build_env.sh  # Script to prepare the environment
│   ├── label_anomaly.py # Label logs and struture script
│   ├── [ELSE FILE:Additional component files used by auto_run]
│   └── run_example.txt  # Examples of how to run AnomalyGen
├── models
│   ├── config/config.json  # Configure API key, base URL, model selection, temperature, etc.
│   ├── prompts  # Different versions of prompts for various stages
│   ├── decoder.py
│   ├── get_resp.py
│   └── model_factory.py
├── mysql
│   └── [MySQL configuration and database interaction files]
├── output
│   ├── enhanced_cfg
│   │   └── merged_enhanced_cfg.json  # Results from enhanced CFG analysiss
│   ├── log_events
│   │   ├── block_labels.csv  # Anomaly labels for Hadoop log sequences
│   │   ├── combined_parsed_logs.csv  # Parsed Hadoop log sequences
│   │   ├── compressed_log_all.json
│   │   ├── final_logs.json  # Final saved output: <exec_flow, log, label>
│   │   ├── hdfs_block_labels.csv  # Anomaly labels for HDFS log sequences
│   │   └── hdfs_combined_parsed_logs.csv  # Parsed HDFS log sequences
|   ├── model_run_logs # Log files for 3 anomaly detection model execution results
├── output_v1 and output_v2 is the ablation logs
├──statistic
│   ├── compress_single_node.py  # Compression for similar logs.
│   ├── standard_all_logs.py  # Standalize all logs.
│   └── log_parser  # Uses LogParser3 Drain for log parsing
├── ablation_v1_compressed_log.json # Ablation(without cot) generated logs 
├── ablation_v2_compressed_log.json # Ablation(without static analysis) generated logs 
├── baseline_compressed_log.json # Baseline logs 

```

**Note:** The provided Hadoop repository can be used directly for step 2 (i.e., using its compiled classes for the java-callgraph2 analysis). If you wish to analyze a different project, compile it and update the project root directory parameter accordingly.

---

## Installation and Setup

### Prerequisites

- Linux environment
- Java (version 1.8 recommended)
- Maven (version 3.3 or later)
- Python 3 with virtual environment support
- MySQL server (for handling the large call graph database)
- Dependencies: `py4j`, `openai`, `python-mysql`, etc.

### Step 1: Environment Installation and Activation

Navigate to the main directory and run the build script to install dependencies and create the required virtual environment:

```bash
cd AnomalyGen-main/main

# Ensure that no other Python virtual environment is active
./build_env.sh  # Installs dependencies and sets up MySQL for callgraph storage
source venv/bin/activate
```

### Step 2: Configure and Run java-callgraph2

This step involves semi-automatically setting up java-callgraph2 for call paths analysis.

#### a) Setup PYTHONPATH

```bash
export PYTHONPATH=$PYTHONPATH:/your/path/to/AnomalyGen-main

# Example
export PYTHONPATH=$PYTHONPATH:/home/ubuntu/AnomalyGen-main
```

#### b) Compile the Target Project


```bash
# Ensure that the environment for the Hadoop project is correctly configured (Java 1.8 and Maven 3.3):
For example:
cd ..
cd hadoop
mvn clean package -DskipTests -Dmaven.compiler.debug=true
```

**Note:** The Hadoop project is large and may take longer to compile.

#### c) Run the java-callgraph2 Script

```bash
cd java-callgraph2
./gradlew gen_run_jar
```

#### d) Collect Classes and Configure java-callgraph2

Return to the project root and run the auto-configuration script:

```bash
cd ..
cd main
python main/auto_callgraph_config.py --project_dir your_project_dir

python main/

# Example
python main/auto_callgraph_config.py --project_dir hadoop(in the main directory )
```

#### e) Modify Configuration and Run Call Graph Construction

Update the following parameters in `java-callgraph2/jar_output_dir/_javacg2_config/config.properties`:

```properties
continue.when.error=true
output.root.path=your_path  # Set this to avoid scattered output directories
output.file.ext=.txt
```

Then, navigate to the output directory and execute:

```bash
cd java-callgraph2/jar_output_dir/
./run.sh
```
More easily, you can directly run auto_global_callgraph_generation.py

The analysis output will typically be generated in a directory named similarly to `cosn-javacg2_merged.jar-output_javacg2`. Note the location of this directory as it will be needed in subsequent steps.

### Step 3: Configure Entry Function and Call Depth

Set the entry function and the maximum call depth for the analysis. It is recommended that the depth does not exceed 5 to avoid excessively large call graphs, which can be computationally expensive to merge and prone to mistakes when processed by large language models.

There are some other examples in main/run_examples.txt

store->
```bash
python3 main/path_store_and_prune.py \
--project_dir zookeeper \
--input_dir zookeeper/zookeeper-javacg2_merged.jar-output_javacg2/
```

prune->analyze->merge and generate your interested log sequences.
(Pruning from a large graph costs time , please be patient)

```bash
python3 main/auto_run.py \
--project_dir hadoop \
--input_dir /your/path/to/cosn-javacg2_merged.jar-output_javacg2 \
--entry_functions "org.apache.hadoop.mapreduce.v2.app.MRAppMaster:main(java.lang.String[])" \
--depth 3

### For examples:

python3 main/auto_run.py \
--project_dir zookeeper \
--entry_functions "org.apache.zookeeper.ClientCnxn$EventThread:processEvent(java.lang.Object)" \
--depth 5

python3 main/auto_run.py \
--project_dir zookeeper \
--entry_functions "org.apache.zookeeper.server.SyncRequestProcessor$1:run()" \
--depth 5
```

**Important:** 
If you have any questions about running the code, please feel free to email me.
---

## Conclusion
By following the steps outlined above, you will set up the environment and configure the necessary components to run AnomalyGen. The project integrates multiple tools and technologies to generate detailed call graphs and log analysis results, making it a powerful tool for software analysis and anomaly detection.

zookeeper version: 上游 ZooKeeper 版本：3.4.5 -> 对应 jar包；
python3 main/auto_prepare.py \
--input_dir ../zookeeper/zookeeper-javacg2_merged.jar-output_javacg2/

export PYTHONPATH=$PYTHONPATH:~/AnomalyGen-main