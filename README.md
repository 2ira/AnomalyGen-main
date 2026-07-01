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
├── hadoop/                        # Project directory to be analyzed
├── java-callgraph2/
│   ├── jar-output_dir/
│   │   └── _javacg2_config/
│   │       └── config.properties  # Main configuration file
│   └── [Tool to generate global call graphs]
├── java-parser/
│   ├── JavaParserServer.java      # Generates single node log-related CFG
│   └── MethodExtractorGateway.java  # Maps signatures to source code
├── main/
│   ├── venv/                      # Python virtual environment (created by build_env.sh)
│   ├── auto_callgraph_config.py   # Collects class files and configures java-callgraph2
│   ├── auto_run.py                # Main execution script
│   ├── auto_global_callgraph_generation.py  # Compile, generate global callgraph, prune
│   ├── auto_run_ablation_v1.py    # Ablation: without CoT
│   ├── auto_run_ablation_v2.py    # Ablation: without static analysis
│   ├── auto_prepare.py            # Store global call path script
│   ├── build_env.sh               # Script to prepare the environment
│   ├── label_anomaly.py           # Label logs and structure script
│   └── run_example.txt            # Examples of how to run AnomalyGen
├── models/
│   ├── config/config.json         # API key, base URL, model, temperature
│   ├── prompts/                   # LLM prompts for each pipeline stage
│   │   ├── merge_node_info.py     # Path merge prompt (CoT + no-CoT baseline)
│   │   ├── generate_node_info.py  # Single-node log sequence generation
│   │   ├── standard_log.py        # Log simulation / standardisation
│   │   └── analysis_code.py       # Java code CFG analysis
│   ├── decoder.py
│   ├── get_resp.py
│   └── model_factory.py
├── mysql/                         # MySQL configuration and database interaction
├── output/                        # Main pipeline output
│   ├── enhanced_cfg/
│   │   └── merged_enhanced_cfg.json
│   ├── log_events/
│   │   ├── block_labels.csv       # Anomaly labels for Hadoop log sequences
│   │   ├── combined_parsed_logs.csv
│   │   ├── compressed_log_all.json
│   │   ├── final_logs.json        # Final output: <exec_flow, log, label>
│   │   ├── hdfs_block_labels.csv
│   │   └── hdfs_combined_parsed_logs.csv
│   └── model_run_logs/            # Anomaly detection model execution results
├── output_v1/                     # Ablation output (without CoT)
├── output_v2/                     # Ablation output (without static analysis)
├── statistic/
│   ├── compress_single_node.py    # Compression for similar logs
│   ├── standard_all_logs.py       # Standardise all logs
│   └── log_parser/                # LogParser3 Drain for log parsing
├── eval_labeling/                 # Supplementary evaluation: label accuracy (M.2)
│   ├── hdfs_recovery_relabel.py   # HDFS baseline vs recovery-aware relabelling
│   ├── zk_recovery_relabel.py     # ZooKeeper relabelling
│   ├── utils.py                   # Shared evaluation utilities
│   ├── README.md                  # Experiment documentation
│   └── eval_results/              # Pre-computed metrics (JSON + CSV)
├── eval_phase2/                   # Supplementary evaluation: Phase II direct eval (M.3)
│   ├── common.py                  # Shared I/O, call-graph parsing, XML parsing
│   ├── build_feasibility_dataset.py  # 40 merge-point benchmark construction
│   ├── run_feasibility_eval.py    # CoT vs no-CoT feasibility prediction
│   ├── build_param_set.py         # Parameter slot extraction + stratified sampling
│   ├── run_param_eval.py          # Rule-based scoring + Cohen's kappa
│   ├── compute_metrics.py         # Aggregate metrics into JSON/CSV
│   ├── README.md                  # Experiment documentation
│   ├── eval_data/                 # Input datasets
│   └── eval_results/              # Pre-computed predictions and metrics
├── ablation_v1_compressed_log.json  # Ablation (without CoT) generated logs
├── ablation_v2_compressed_log.json  # Ablation (without static analysis) generated logs
└── baseline_compressed_log.json     # Baseline logs
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

## Supplementary Evaluation Experiments

Two supplementary experiments are provided to independently validate AnomalyGen's label quality (M.2) and Phase II pipeline correctness (M.3).

### M.2: Label Accuracy Evaluation (`eval_labeling/`)

Validates AnomalyGen's automatic anomaly labelling by comparing a **baseline rule** (ERROR-level keyword matching) against a **recovery-aware rule** (which accounts for benign error-recovery patterns) on hand-reviewed ground truth.

| System    | Sessions | Ground-truth basis |
|-----------|----------|--------------------|
| HDFS      | 106      | 10 semantically reviewed sessions + access-denied heuristic |
| ZooKeeper | 17+      | 17 hand-reviewed sessions with rationale |

**How to run:**

```bash
cd AnomalyGen-main

# HDFS (requires output_v1/ablation/baseline/parsed_logs/)
python eval_labeling/hdfs_recovery_relabel.py

# ZooKeeper (requires output/zookeeper/)
python eval_labeling/zk_recovery_relabel.py
```

Pre-computed results are in `eval_labeling/eval_results/`.  See `eval_labeling/README.md` for details.

### M.3: Phase II Direct Evaluation (`eval_phase2/`)

Directly evaluates two aspects of Phase II's output quality:

**Experiment A — Path Feasibility (CoT vs no-CoT):**  
Tests whether CoT reasoning improves the LLM's ability to identify feasible execution paths at merge points.

- Benchmark: 40 HDFS merge points (27 original + 13 extended) with manual ground truth
- Metrics: Accuracy, Precision, Recall, F1

```bash
cd AnomalyGen-main

# Build the benchmark dataset (if not already present)
python eval_phase2/build_feasibility_dataset.py

# Run evaluation (requires API key in models/config/config.json)
python eval_phase2/run_feasibility_eval.py --variant cot
python eval_phase2/run_feasibility_eval.py --variant nocot

# Generate comparison report
python eval_phase2/run_feasibility_eval.py --report
```

**Experiment B — Parameter Quality:**  
Assesses whether LLM-filled template parameters are semantically valid and contextually consistent.

- Sample: 207 parameter slots stratified by semantic type (hex, path, int, nodeid, etc.)
- Dimensions: type validity (format conformance) + cross-entry consistency
- Method: fully automated rule-based scoring (zero LLM re-runs)

```bash
cd AnomalyGen-main

# Extract and sample parameter slots (requires parsed_logs CSVs)
python eval_phase2/build_param_set.py

# Score sampled slots
python eval_phase2/run_param_eval.py

# Aggregate all metrics
python eval_phase2/compute_metrics.py
```

Pre-computed results are in `eval_phase2/eval_results/`.  See `eval_phase2/README.md` for details.

---

## Conclusion
By following the steps outlined above, you will set up the environment and configure the necessary components to run AnomalyGen. The project integrates multiple tools and technologies to generate detailed call graphs and log analysis results, making it a powerful tool for software analysis and anomaly detection.

Additionally:
ZooKeeper version 3.4.5
