# AnomalyGen-main

\documentclass{article}
\usepackage[utf8]{inputenc}
\usepackage{listings}
\usepackage{xcolor}
\usepackage{hyperref}
\usepackage{graphicx}
\usepackage{fontspec}
\setmonofont{Consolas}

\definecolor{codegreen}{rgb}{0,0.6,0}
\definecolor{codegray}{rgb}{0.5,0.5,0.5}
\definecolor{codepurple}{rgb}{0.58,0,0.82}
\definecolor{backcolour}{rgb}{0.95,0.95,0.92}

\lstdefinestyle{mystyle}{
    backgroundcolor=\color{backcolour},   
    commentstyle=\color{codegreen},
    keywordstyle=\color{magenta},
    numberstyle=\tiny\color{codegray},
    stringstyle=\color{codepurple},
    basicstyle=\ttfamily\footnotesize,
    breakatwhitespace=false,         
    breaklines=true,                 
    captionpos=b,                    
    keepspaces=true,                 
    numbers=left,                    
    numbersep=5pt,                  
    showspaces=false,                
    showstringspaces=false,
    showtabs=false,                  
    tabsize=2
}
\lstset{style=mystyle}

\title{AnomalyGen: Automated Anomaly Detection in Distributed Systems}
\author{}
\date{}

\begin{document}

\maketitle

\section{Overview}
AnomalyGen is a comprehensive framework for analyzing system behaviors through call graph analysis and machine learning. The system features:

\begin{itemize}
\item Multi-stage processing pipeline with Java static analysis
\item Integration with large language models (OpenAI)
\item Log sequence analysis and anomaly detection
\item MySQL-based call graph storage
\end{itemize}

\section{Project Structure}
The project directory is organized as follows:
\begin{verbatim}
AnomalyGen-main/
│
├── hadoop
│   └── [project_dir to be analyzed]
│
├── java-callgraph2
│   ├── jar-output_dir
│   │   └── _javacg2_config/
│   │       └── config.properties  % Main configuration file
│   └── [Tool to generate global call graphs]
│
├── java-parser
│   ├── JavaParserServer.java             % Generates single node log-related CFG
│   └── MethodExtractorGateway.java       % Maps signatures to source code
│
├── main
│   ├── venv                              % Python virtual environment for the entire project
│   ├── auto_callgraph_config.py          % Auto-collects class files and configures java-callgraph2
│   ├── auto_run.py                       % Main execution script
│   ├── build_env.sh                      % Script to prepare the environment
│   ├── [Additional component files used by auto\_run]
│   └── run\_example.txt                  % Examples of how to run AnomalyGen
│
├── models
│   ├── config/config.json                % Configure API key, base URL, model selection, temperature, etc.
│   ├── prompts                          % Different versions of prompts for various stages
│   ├── decoder.py
│   ├── get_resp.py
│   └── model_factory.py
│
├── mysql
│   └── [MySQL configuration and database interaction files]
│
├── output
│   ├── enhanced\_cfg
│   │   └── merged\_enhanced\_cfg.json     % All results from enhanced CFG analysis
│   ├── hadoop
│   │   └── collect\_class.txt             % List of all collected classes
│   ├── log\_events
│   │   ├── block\_labels.csv              % Anomaly labels for Hadoop log sequences
│   │   ├── combined\_parsed\_logs.csv     % Parsed Hadoop log sequences
│   │   ├── compressed\_log\_all.json
│   │   ├── final\_logs.json               % Final saved output: <exec\_flow, log, label>
│   │   ├── hdfs\_block\_labels.csv        % Anomaly labels for HDFS log sequences
│   │   └── hdfs\_combined\_parsed\_logs.csv % Parsed HDFS log sequences
│   └── statistic
│       ├── compress\_single\_node.py       % Compression for similar logs
│       └── log\_parser                    % Uses LogParser3 Drain for log parsing
\end{verbatim}

\noindent\textbf{Note:} The provided Hadoop repository can be directly used for step 2 (i.e., using its compiled classes for the java-callgraph2 analysis). If you wish to analyze a different project, compile it and update the project root directory parameter accordingly.

\section{Installation and Setup}
\subsection{Prerequisites}
\begin{itemize}[leftmargin=*, labelsep=5mm]
    \item Linux environment
    \item Java (version 1.8 recommended)
    \item Maven (version 3.3 or later)
    \item Python 3 with virtual environment support
    \item MySQL server (for handling the large call graph database)
    \item Dependencies: \texttt{py4j}, \texttt{openai}, \texttt{python-mysql}, etc.
\end{itemize}

\subsection{Step 1: Environment Installation and Activation}
Navigate to the main directory and run the build script to install dependencies and create the required virtual environment:
\begin{lstlisting}[language=bash]
cd AnomalyGen-main/main
# Ensure that no other Python virtual environment is active
./build_env.sh   % This installs python-venv, python-mysql, openai, py4j, and other dependencies; also creates a user and a database for storing the huge callgraph.
source venv/bin/activate
\end{lstlisting}

\subsection{Step 2: Configure and Run java-callgraph2}
This step involves semi-automatically setting up java-callgraph2 for call paths analysis.

\paragraph{a) Setup pythonpath:}
\begin{lstlisting}[language=bash]
export PYTHONPATH=$PYTHONPATH:/your/path/to/AnomalyGen-main
# Example:
export PYTHONPATH=$PYTHONPATH:/home/ubuntu/AnomalyGen-main
\end{lstlisting}

\paragraph{b) Compile the Target Project:}
Ensure that the environment for the Hadoop project is correctly configured (Java 1.8 and Maven 3.3):
\begin{lstlisting}[language=bash]
mvn clean package -DskipTests -Dmaven.compiler.debug=true
\end{lstlisting}
\noindent\textbf{Note:} The Hadoop project is large and may take a longer time to compile.

\paragraph{c) Run the java-callgraph2 Script:}
From the \texttt{java-callgraph2} directory:
\begin{lstlisting}[language=bash]
cd java-callgraph2
./gradlew gen_run_jar
\end{lstlisting}

\paragraph{d) Collect Classes and Configure java-callgraph2:}
Return to the project root and run the auto-configuration script:
\begin{lstlisting}[language=bash]
cd ..
python main/auto_callgraph_config.py --project_dir your_project_dir
# Example: python main/auto_callgraph_config.py --project_dir hadoop
\end{lstlisting}

\paragraph{e) Modify Configuration and Run Call Graph Construction:}
Update the following parameters in \texttt{java-callgraph2/jar-output\_dir/\_javacg2\_config/config.properties}:
\begin{itemize}[leftmargin=*, labelsep=5mm]
    \item \texttt{continue.when.error=true}
    \item \texttt{output.root.path=your\_path} (Set this to avoid scattered output directories)
    \item \texttt{output.file.ext=.txt}
\end{itemize}
Then, navigate to the output directory and execute:
\begin{lstlisting}[language=bash]
cd java-callgraph2/jar-output_dir/
./run.sh
\end{lstlisting}
The analysis output will typically be generated in a directory named similar to \texttt{cosn-javacg2\_merged.jar-output\_javacg2}. Note the location of this directory as it will be needed in subsequent steps.

\subsection{Step 3: Configure Entry Function and Call Depth}
Set the entry function and the maximum call depth for the analysis. It is recommended that the depth does not exceed 5 to avoid excessively large call graphs, which can be computationally expensive to merge and prone to errors when processed by large language models.

\noindent\textbf{Important:} Modify the logic so that the database is not rebuilt every time. Consider splitting the process into two files to handle database initialization and incremental updates separately.

\section{Conclusion}
By following the steps outlined above, you will set up the environment and configure the necessary components to run AnomalyGen. The project integrates multiple tools and technologies to generate detailed call graphs and log analysis results, making it a powerful tool for software analysis and anomaly detection.

\end{document}