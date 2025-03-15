import sys
import re
from py4j.java_gateway import JavaGateway
from py4j.java_collections import JavaList, JavaObject
import json
import logging
logging.basicConfig(filename='failed_parsing.log', level=logging.ERROR,format='%(asctime)s - %(levelname)s - %(message)s')


import re

def remove_comments_and_strings(java_code):
    code = re.sub(r'//.*', '', java_code)
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    code = re.sub(r'"(?:\\.|[^"])*"', '', code)
    return code

def has_method_body(java_code):
    code = remove_comments_and_strings(java_code)
    pattern = re.compile(r'\(.*?\).*?\{')
    return bool(pattern.search(code))


def analyze_java_code(java_code):
    if not has_method_body(java_code):
        error_message = f"no method body,代码内容:\n{java_code}"
        print(error_message)
        logging.error(error_message)
        return java_code
    gateway = JavaGateway()
    JavaListType = gateway.jvm.java.util.List
    java_parser_server = gateway.entry_point
    full_code = f"""
package com.example;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
public class MyClass {{ {java_code} }}"""

    print("full_code.......")
    print(full_code)

    try:
        controlflow = java_parser_server.analyzeControlFlow(full_code)
        controlflow = str(controlflow)
        return controlflow
    except Exception as e:
        error_message = f"分析 Java 代码时发生异常，跳过该函数。错误信息: {e}\n代码内容:\n{java_code}"
        print(error_message)
        logging.error(error_message)
        return java_code

def main():
    source_code=""" /**
   * Create the common {@link ContainerLaunchContext} for all attempts.
   * @param applicationACLs 
   */
  private static ContainerLaunchContext createCommonContainerLaunchContext(
      Map<ApplicationAccessType, String> applicationACLs, Configuration conf,
      Token<JobTokenIdentifier> jobToken,
      final org.apache.hadoop.mapred.JobID oldJobId,
      Credentials credentials) {
    // Application resources
    Map<String, LocalResource> localResources = 
        new HashMap<String, LocalResource>();
    
    // Application environment
    Map<String, String> environment;

    // Service data
    Map<String, ByteBuffer> serviceData = new HashMap<String, ByteBuffer>();

    // Tokens
    ByteBuffer taskCredentialsBuffer = ByteBuffer.wrap(new byte[]{});
    try {

      configureJobJar(conf, localResources);

      configureJobConf(conf, localResources, oldJobId);

      // Setup DistributedCache
      MRApps.setupDistributedCache(conf, localResources);

      taskCredentialsBuffer =
          configureTokens(jobToken, credentials, serviceData);

       // Log.info("test api");

      addExternalShuffleProviders(conf, serviceData);

      environment = configureEnv(conf);

    } catch (IOException e) {
      throw new YarnRuntimeException(e);
      
    }

    // Construct the actual Container
    // The null fields are per-container and will be constructed for each
    // container separately.
    log.info("User login: {}", username);
    ContainerLaunchContext container =
        ContainerLaunchContext.newInstance(localResources, environment, null,
            serviceData, taskCredentialsBuffer, applicationACLs);

    return container;
  }
"""
    result = analyze_java_code(source_code)
    print(result)
